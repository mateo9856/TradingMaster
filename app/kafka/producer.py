"""
Exchange → Kafka producer

Reads exchange and symbol configuration from the database (exchanges + symbols tables)
instead of hardcoded EXCHANGE_CONFIG. Adding a new exchange or symbol only
requires a DB row — no code change or deploy needed.

Exchange streaming methods:
  - binance:  watchOHLCVForSymbols (multi)
  - kraken:   watchOHLCV per symbol (ohlcv)
  - coinbase: watchTrades → manual 1m candle aggregation (trades)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import ccxt.pro as ccxtpro
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from sqlalchemy import select

from app.config import KAFKA_BOOTSTRAP_SERVERS, EXCHANGE_CREDENTIALS
from app.metrics import kafka_messages_produced_total, kafka_reconnects_total
from app.models.database import AsyncSessionLocal
from app.models.exchange import Exchange, Symbol
from app.tracing import inject_traceparent_headers, tracer

logger = logging.getLogger(__name__)

# Candle state for trade-based aggregation (Coinbase)
_candle_state: dict = {}


def _topic_name(exchange: str, symbol: str) -> str:
    return f"{exchange}.{symbol.replace('/', '')}.candles"


async def _load_exchange_config() -> list[dict]:
    """
    Loads enabled exchanges and their enabled symbols from the database.
    Returns a list of dicts ready to use for streaming.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Exchange).where(Exchange.enabled == True)
        )
        exchanges = result.scalars().all()

        config = []
        for exc in exchanges:
            sym_result = await db.execute(
                select(Symbol).where(
                    Symbol.exchange_id == exc.id,
                    Symbol.enabled == True,
                )
            )
            symbols = sym_result.scalars().all()

            config.append({
                "name":     exc.name,
                "method":   exc.method,
                "symbols":  [s.ticker for s in symbols],
                "interval": symbols[0].interval if symbols else "1m",
            })

    logger.info(f"Loaded exchange config from DB: {[c['name'] for c in config]}")
    return config


async def _build_topic_list(config: list[dict]) -> list[str]:
    topics = []
    for exc in config:
        for symbol in exc["symbols"]:
            topics.append(_topic_name(exc["name"], symbol))
    return topics


async def _create_topics(config: list[dict]) -> None:
    """Creates all required Kafka topics based on DB config."""
    topics = await _build_topic_list(config)
    admin = AIOKafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        await admin.create_topics([
            NewTopic(name=t, num_partitions=1, replication_factor=1)
            for t in topics
        ])
        logger.info(f"Created Kafka topics: {topics}")
    except TopicAlreadyExistsError:
        logger.info("Kafka topics already exist — skipping creation")
    except Exception as e:
        logger.warning(f"Topic creation warning: {e}")
    finally:
        await admin.close()


async def _send_candle(
    producer: AIOKafkaProducer,
    exchange_id: str,
    symbol: str,
    interval: str,
    ohlcv: list,
) -> None:
    ts, open_, high, low, close, volume = ohlcv
    timestamp = datetime.fromtimestamp(ts / 1000, timezone.utc).replace(tzinfo=None)
    payload = {
        "exchange":    exchange_id,
        "ticker":      symbol,
        "interval":    interval,
        # Database timestamps are TIMESTAMP WITHOUT TIME ZONE values stored as UTC.
        "timestamp":   timestamp.isoformat(),
        "open_price":  open_,
        "high_price":  high,
        "low_price":   low,
        "close_price": close,
        "volume":      volume,
    }
    topic = _topic_name(exchange_id, symbol)
    with tracer.start_as_current_span(
        "kafka.produce",
        attributes={
            "messaging.system": "kafka",
            "messaging.destination": topic,
            "exchange": exchange_id,
            "ticker": symbol,
            "interval": interval,
        },
    ):
        headers = inject_traceparent_headers()
        await producer.send(topic, value=json.dumps(payload).encode("utf-8"), headers=headers)
    kafka_messages_produced_total.labels(exchange=exchange_id, ticker=symbol, interval=interval).inc()
    logger.debug(f"[{exchange_id}] → {topic} close={close}")


async def _stream_multi(exchange, exchange_id, symbols, producer, interval):
    """Binance — watchOHLCVForSymbols."""
    while True:
        candles = await exchange.watch_ohlcv_for_symbols(
            [[s, interval] for s in symbols]
        )
        for symbol, timeframes in candles.items():
            for tf, ohlcv_list in timeframes.items():
                for ohlcv in ohlcv_list:
                    await _send_candle(producer, exchange_id, symbol, tf, ohlcv)


async def _stream_ohlcv(exchange, exchange_id, symbol, producer, interval):
    """Kraken — watchOHLCV per symbol."""
    while True:
        for ohlcv in await exchange.watch_ohlcv(symbol, interval):
            await _send_candle(producer, exchange_id, symbol, interval, ohlcv)


async def _stream_trades(exchange, exchange_id, symbol, producer, interval="1m"):
    """Coinbase — watchTrades → manual 1m candle aggregation."""
    global _candle_state
    if exchange_id not in _candle_state:
        _candle_state[exchange_id] = {}
    if symbol not in _candle_state[exchange_id]:
        _candle_state[exchange_id][symbol] = {}

    buckets = _candle_state[exchange_id][symbol]

    while True:
        trades = await exchange.watch_trades(symbol)
        for trade in trades:
            ts_ms  = trade["timestamp"]
            price  = trade["price"]
            amount = trade["amount"]
            minute_ts = (ts_ms // 60_000) * 60_000

            for old_ts in [t for t in list(buckets) if t < minute_ts]:
                c = buckets.pop(old_ts)
                await _send_candle(
                    producer, exchange_id, symbol, interval,
                    [old_ts, c["open"], c["high"], c["low"], c["close"], c["volume"]],
                )

            if minute_ts not in buckets:
                buckets[minute_ts] = {
                    "open": price, "high": price,
                    "low":  price, "close": price, "volume": amount,
                }
            else:
                b = buckets[minute_ts]
                b["high"]   = max(b["high"], price)
                b["low"]    = min(b["low"],  price)
                b["close"]  = price
                b["volume"] += amount


async def _stream_exchange(exc_config: dict, producer: AIOKafkaProducer) -> None:
    """Streams candles from one exchange. Auto-reconnects on error."""
    exchange_id = exc_config["name"]
    symbols     = exc_config["symbols"]
    interval    = exc_config["interval"]
    method      = exc_config["method"]

    credentials = EXCHANGE_CREDENTIALS.get(exchange_id, {})
    exchange: ccxtpro.Exchange = getattr(ccxtpro, exchange_id)(credentials)

    logger.info(f"[{exchange_id}] symbols={symbols} interval={interval} method={method}")

    while True:
        try:
            await exchange.load_markets()

            if method == "multi":
                await _stream_multi(exchange, exchange_id, symbols, producer, interval)
            elif method == "trades":
                await asyncio.gather(*[
                    _stream_trades(exchange, exchange_id, symbol, producer, interval)
                    for symbol in symbols
                ])
            else:
                await asyncio.gather(*[
                    _stream_ohlcv(exchange, exchange_id, symbol, producer, interval)
                    for symbol in symbols
                ])

        except Exception as e:
            kafka_reconnects_total.labels(exchange=exchange_id).inc()
            logger.warning(f"[{exchange_id}] Stream error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass


async def run_producer() -> None:
    """Loads config from DB, creates topics, starts all exchange streams."""
    config = await _load_exchange_config()

    if not config:
        logger.warning("No enabled exchanges found in DB — producer idle")
        return

    await _create_topics(config)

    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    logger.info("Kafka producer started")

    try:
        await asyncio.gather(*[
            _stream_exchange(exc, producer)
            for exc in config
        ])
    finally:
        await producer.stop()
        logger.info("Kafka producer stopped")
