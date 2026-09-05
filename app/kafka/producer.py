"""
Exchange → Kafka producer

Uses CCXT Pro to stream live OHLCV candles from multiple exchanges.

Exchange-specific notes:
  - Binance:  watchOHLCVForSymbols — native multi-symbol OHLCV stream
  - Kraken:   watchOHLCV per symbol — native OHLCV stream
  - Coinbase: watchOHLCV not available in Python ccxt 4.x (watchOHLCV: False)
              Uses watchTrades instead and aggregates into 1m candles manually.
              Symbols use USD pairs (BTC/USD not BTC/USDT).

Topic naming: {exchange}.{ticker_normalized}.candles
Examples:     binance.BTCUSDT.candles
              coinbase.BTCUSD.candles
"""

import asyncio
import json
import logging
from datetime import datetime

import ccxt.pro as ccxtpro
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from app.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    WATCH_SYMBOLS,
    WATCH_EXCHANGES,
    EXCHANGE_CREDENTIALS,
)

logger = logging.getLogger(__name__)

# Per-exchange configuration
EXCHANGE_CONFIG: dict = {
    "binance": {
        "symbols":  ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
        "interval": "1m",
        "method":   "multi",    # watchOHLCVForSymbols
    },
    "kraken": {
        "symbols":  ["BTC/USDT", "ETH/USDT"],
        "interval": "1m",
        "method":   "ohlcv",    # watchOHLCV per symbol
    },
    "coinbase": {
        "symbols":  ["BTC/USD", "ETH/USD"],
        "interval": "1m",
        "method":   "trades",   # watchTrades → manual candle aggregation
    },
}

# Candle state for trade-based aggregation
# {exchange_id: {symbol: {minute_ts: {open, high, low, close, volume}}}}
_candle_state: dict = {}


def _topic_name(exchange: str, symbol: str) -> str:
    """BTC/USDT → BTCUSDT, topic → binance.BTCUSDT.candles"""
    return f"{exchange}.{symbol.replace('/', '')}.candles"


def _build_topic_list() -> list[str]:
    topics = []
    for exchange_id in WATCH_EXCHANGES:
        config = EXCHANGE_CONFIG.get(exchange_id, {})
        for symbol in config.get("symbols", WATCH_SYMBOLS):
            topics.append(_topic_name(exchange_id, symbol))
    return topics


async def _create_topics() -> None:
    """Creates all Kafka topics on startup — idempotent."""
    topics = _build_topic_list()
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
    """Send one OHLCV candle to Kafka."""
    ts, open_, high, low, close, volume = ohlcv
    payload = {
        "exchange":    exchange_id,
        "ticker":      symbol,
        "interval":    interval,
        "timestamp":   datetime.utcfromtimestamp(ts / 1000).isoformat(),
        "open_price":  open_,
        "high_price":  high,
        "low_price":   low,
        "close_price": close,
        "volume":      volume,
    }
    topic = _topic_name(exchange_id, symbol)
    await producer.send(topic, value=json.dumps(payload).encode("utf-8"))
    logger.debug(f"[{exchange_id}] → {topic} close={close}")


# ── Streaming methods ─────────────────────────────────────────────────────────

async def _stream_multi(
    exchange: ccxtpro.Exchange,
    exchange_id: str,
    symbols: list[str],
    producer: AIOKafkaProducer,
    interval: str,
) -> None:
    """Binance — watchOHLCVForSymbols."""
    while True:
        candles = await exchange.watch_ohlcv_for_symbols(
            [[s, interval] for s in symbols]
        )
        for symbol, timeframes in candles.items():
            for tf, ohlcv_list in timeframes.items():
                for ohlcv in ohlcv_list:
                    await _send_candle(producer, exchange_id, symbol, tf, ohlcv)


async def _stream_ohlcv(
    exchange: ccxtpro.Exchange,
    exchange_id: str,
    symbol: str,
    producer: AIOKafkaProducer,
    interval: str,
) -> None:
    """Kraken — watchOHLCV per symbol."""
    while True:
        for ohlcv in await exchange.watch_ohlcv(symbol, interval):
            await _send_candle(producer, exchange_id, symbol, interval, ohlcv)


async def _stream_trades(
    exchange: ccxtpro.Exchange,
    exchange_id: str,
    symbol: str,
    producer: AIOKafkaProducer,
    interval: str = "1m",
) -> None:
    """
    Coinbase — watchTrades → manual 1m candle aggregation.
    Each trade updates the current minute bucket. When a new minute
    starts the completed candle is flushed to Kafka.
    """
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

            # Floor to current minute
            minute_ts = (ts_ms // 60_000) * 60_000

            # Flush completed minutes
            for old_ts in [t for t in list(buckets) if t < minute_ts]:
                c = buckets.pop(old_ts)
                await _send_candle(
                    producer, exchange_id, symbol, interval,
                    [old_ts, c["open"], c["high"], c["low"], c["close"], c["volume"]],
                )

            # Update or create current bucket
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


# ── Main stream dispatcher ────────────────────────────────────────────────────

async def _stream_exchange(
    exchange_id: str,
    producer: AIOKafkaProducer,
) -> None:
    """Opens connection to one exchange and streams candles. Auto-reconnects."""
    config   = EXCHANGE_CONFIG.get(exchange_id, {})
    symbols  = config.get("symbols",  WATCH_SYMBOLS)
    interval = config.get("interval", "1m")
    method   = config.get("method",   "ohlcv")

    credentials = EXCHANGE_CREDENTIALS.get(exchange_id, {})
    exchange: ccxtpro.Exchange = getattr(ccxtpro, exchange_id)(credentials)

    logger.info(f"[{exchange_id}] symbols={symbols} interval={interval} method={method}")

    while True:
        try:
            await exchange.load_markets()

            if method == "multi":
                await _stream_multi(exchange, exchange_id, symbols, producer, interval)

            elif method == "trades":
                # One coroutine per symbol sharing the same exchange connection
                await asyncio.gather(*[
                    _stream_trades(exchange, exchange_id, symbol, producer, interval)
                    for symbol in symbols
                ])

            else:  # "ohlcv"
                await asyncio.gather(*[
                    _stream_ohlcv(exchange, exchange_id, symbol, producer, interval)
                    for symbol in symbols
                ])

        except Exception as e:
            logger.warning(f"[{exchange_id}] Stream error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)

        finally:
            try:
                await exchange.close()
            except Exception:
                pass


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_producer() -> None:
    """Creates Kafka topics then starts streaming from all configured exchanges."""
    await _create_topics()

    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    logger.info("Kafka producer started")

    try:
        await asyncio.gather(*[
            _stream_exchange(exchange_id, producer)
            for exchange_id in WATCH_EXCHANGES
        ])
    finally:
        await producer.stop()
        logger.info("Kafka producer stopped")