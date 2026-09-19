"""
Exchange → Kafka producer — the unified market feed.

Reads exchange and symbol configuration from the database (exchanges + symbols
tables) and re-reads it every PRODUCER_CONFIG_REFRESH_SECONDS, so adding,
enabling or disabling a market through the API takes effect without a restart.

Every candle is published in one unified format, whatever the source exchange:
  - ticker is the unified USD market ("BTC/USD"); the exchange's own market
    ("BTC/USDT") is kept in source_ticker
  - prices are converted to USD (see fx_rates.py) and, like volume, sent as
    fixed-point strings with 8 decimals ("65000.10000000")
  - topics are {exchange}.{UNIFIED}.candles, e.g. binance.BTCUSD.candles

Intervals (30s, 1m, 5m, 1h, 1d — one symbols row per ticker+interval) use the
exchange's native candle stream when CCXT supports that timeframe there, and
are otherwise built from the trade stream (30s everywhere; every interval on
trade-only exchanges):
  - binance:  watchOHLCVForSymbols (multi)
  - kraken:   watchOHLCV per symbol+interval (ohlcv)
  - coinbase: watchTrades → candle aggregation (trades)
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

from app.config import EXCHANGE_CREDENTIALS, KAFKA_BOOTSTRAP_SERVERS, PRODUCER_CONFIG_REFRESH_SECONDS
from app.helpers.intervals import SUPPORTED_INTERVALS, bucket_start
from app.helpers.markets import QUOTE_PREFERENCE, UNIFIED_QUOTE, split_symbol, topic_ticker, unified_ticker
from app.helpers.prices import format_decimal, to_decimal
from app.helpers.tasks import run_all
from app.kafka.fx_rates import FxRates, watch_fx_rates
from app.metrics import candles_skipped_total, kafka_messages_produced_total, kafka_reconnects_total
from app.models.database import AsyncSessionLocal
from app.models.exchange import Exchange, Symbol
from app.tracing import inject_traceparent_headers, tracer

logger = logging.getLogger(__name__)

# Version of the unified message format — the Flink job only stores messages
# carrying this version (older float/native-ticker messages are skipped).
SCHEMA_VERSION = 2

_RECONNECT_DELAY_SECONDS = 5
_NO_MARKETS_RETRY_SECONDS = 60

# Candle state for trade-based aggregation: exchange → symbol → interval → buckets
_candle_state: dict = {}

# Shared quote → USD rates, kept fresh by watch_fx_rates() while the producer runs.
fx_rates = FxRates()


def _topic_name(exchange: str, symbol: str) -> str:
    return f"{exchange}.{topic_ticker(symbol)}.candles"


# ── Configuration ────────────────────────────────────────────────────────────

def _quote_rank(symbol: str) -> int:
    """USD markets win over USDT, which win over USDC, when two map to one unified ticker."""
    return QUOTE_PREFERENCE.index(split_symbol(symbol)[1])


def _group_symbols(exchange_name: str, rows) -> dict[str, list[str]]:
    """
    Groups (ticker, interval) rows into {ticker: [intervals]}, dropping rows the
    unified feed can't publish: unsupported intervals, non-USD quotes, and a
    second market on the same exchange that maps to an already-used unified
    ticker (e.g. kraken BTC/USDT when BTC/USD is configured too).
    """
    grouped: dict[str, list[str]] = {}
    for ticker, interval in rows:
        if interval not in SUPPORTED_INTERVALS:
            logger.warning(f"[{exchange_name}] skipping {ticker} — unsupported interval '{interval}'")
            continue
        try:
            split_symbol(ticker)
        except ValueError as e:
            logger.warning(f"[{exchange_name}] skipping {ticker} — {e}")
            continue
        grouped.setdefault(ticker, [])
        if interval not in grouped[ticker]:
            grouped[ticker].append(interval)

    chosen: dict[str, str] = {}
    for ticker in sorted(grouped, key=lambda t: (unified_ticker(t), _quote_rank(t))):
        unified = unified_ticker(ticker)
        if unified in chosen:
            logger.warning(
                f"[{exchange_name}] skipping {ticker} — {chosen[unified]} already feeds {unified}"
            )
            continue
        chosen[unified] = ticker

    return {
        ticker: sorted(grouped[ticker], key=SUPPORTED_INTERVALS.index)
        for ticker in sorted(chosen.values())
    }


async def _load_exchange_config() -> list[dict]:
    """
    Loads enabled exchanges and their enabled symbols from the database.
    Returns [{"name", "method", "symbols": {ticker: [intervals]}}], skipping
    exchanges with nothing to stream.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Exchange.name, Exchange.method, Symbol.ticker, Symbol.interval)
            .join(Symbol, Symbol.exchange_id == Exchange.id)
            .where(Exchange.enabled == True, Symbol.enabled == True)  # noqa: E712
            .order_by(Exchange.name, Symbol.ticker, Symbol.interval)
        )
        rows = result.all()

    by_exchange: dict[str, dict] = {}
    for name, method, ticker, interval in rows:
        entry = by_exchange.setdefault(name, {"name": name, "method": method, "rows": []})
        entry["rows"].append((ticker, interval))

    config = []
    for entry in by_exchange.values():
        symbols = _group_symbols(entry["name"], entry["rows"])
        if symbols:
            config.append({"name": entry["name"], "method": entry["method"], "symbols": symbols})

    logger.info(f"Loaded exchange config from DB: {[c['name'] for c in config]}")
    return config


async def _build_topic_list(config: list[dict]) -> list[str]:
    topics = []
    for exc in config:
        for symbol in exc["symbols"]:
            topic = _topic_name(exc["name"], symbol)
            if topic not in topics:
                topics.append(topic)
    return topics


async def _create_topics(config: list[dict]) -> None:
    """Creates all required Kafka topics based on DB config."""
    topics = await _build_topic_list(config)
    if not topics:
        return
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


# ── Unified message format ───────────────────────────────────────────────────

def build_unified_payload(
    exchange_id: str,
    source_symbol: str,
    interval: str,
    ohlcv: list,
    fx_rate,
) -> dict:
    """
    Converts one exchange OHLCV row to the unified feed message: USD prices
    (native price × fx_rate) and base-currency volume, as 8-decimal strings.
    Raises ValueError if the row or rate can't be represented.
    """
    try:
        ts, open_, high, low, close, volume = ohlcv
        timestamp = datetime.fromtimestamp(ts / 1000, timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"Invalid OHLCV row {ohlcv!r}") from exc

    rate = to_decimal(fx_rate)
    if rate <= 0:
        raise ValueError(f"FX rate must be positive, got {fx_rate!r}")

    def usd(price) -> str:
        return format_decimal(to_decimal(price) * rate)

    return {
        "schema_version": SCHEMA_VERSION,
        "exchange":       exchange_id,
        "ticker":         unified_ticker(source_symbol),
        "source_ticker":  source_symbol,
        "quote_currency": UNIFIED_QUOTE,
        "fx_rate":        format_decimal(rate),
        "interval":       interval,
        # Database timestamps are TIMESTAMP WITHOUT TIME ZONE values stored as UTC.
        "timestamp":      timestamp.isoformat(),
        "open_price":     usd(open_),
        "high_price":     usd(high),
        "low_price":      usd(low),
        "close_price":    usd(close),
        "volume":         format_decimal(volume),
    }


async def _send_candle(
    producer: AIOKafkaProducer,
    exchange_id: str,
    symbol: str,
    interval: str,
    ohlcv: list,
) -> None:
    try:
        rate, _ = fx_rates.get(split_symbol(symbol)[1])
        payload = build_unified_payload(exchange_id, symbol, interval, ohlcv, rate)
    except ValueError as e:
        candles_skipped_total.labels(exchange=exchange_id).inc()
        logger.warning(f"[{exchange_id}] dropping {symbol} {interval} candle: {e}")
        return

    topic = _topic_name(exchange_id, symbol)
    with tracer.start_as_current_span(
        "kafka.produce",
        attributes={
            "messaging.system": "kafka",
            "messaging.destination": topic,
            "exchange": exchange_id,
            "ticker": payload["ticker"],
            "source_ticker": symbol,
            "interval": interval,
        },
    ):
        headers = inject_traceparent_headers()
        await producer.send(topic, value=json.dumps(payload).encode("utf-8"), headers=headers)
    kafka_messages_produced_total.labels(exchange=exchange_id, ticker=payload["ticker"], interval=interval).inc()
    logger.debug(f"[{exchange_id}] → {topic} close={payload['close_price']}")


# ── Exchange streams ─────────────────────────────────────────────────────────

def _split_intervals(exchange, method: str, intervals: list[str]) -> tuple[list[str], list[str]]:
    """(native, from_trades): native if the exchange streams that timeframe, else built from trades."""
    if method == "trades":
        return [], list(intervals)
    timeframes = getattr(exchange, "timeframes", None) or {}
    native = [i for i in intervals if i in timeframes]
    from_trades = [i for i in intervals if i not in timeframes]
    return native, from_trades


def _available_symbols(exchange, exchange_id: str, symbols: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drops tickers the exchange doesn't list, so one bad pair can't crash-loop the whole exchange."""
    markets = getattr(exchange, "markets", None) or {}
    available = {}
    for ticker, intervals in symbols.items():
        if ticker in markets:
            available[ticker] = intervals
        else:
            logger.warning(f"[{exchange_id}] market {ticker} not listed on the exchange — skipping")
    return available


async def _stream_multi(exchange, exchange_id, subscriptions, producer):
    """Binance — watchOHLCVForSymbols over every [symbol, timeframe] pair."""
    while True:
        candles = await exchange.watch_ohlcv_for_symbols(subscriptions)
        for symbol, timeframes in candles.items():
            for tf, ohlcv_list in timeframes.items():
                for ohlcv in ohlcv_list:
                    await _send_candle(producer, exchange_id, symbol, tf, ohlcv)


async def _stream_ohlcv(exchange, exchange_id, symbol, producer, interval):
    """Kraken — watchOHLCV per symbol and interval."""
    while True:
        for ohlcv in await exchange.watch_ohlcv(symbol, interval):
            await _send_candle(producer, exchange_id, symbol, interval, ohlcv)


async def _stream_trades(exchange, exchange_id, symbol, producer, intervals):
    """
    watchTrades → candle aggregation for every interval in `intervals` from a
    single trade stream. A candle is sent once a trade for a later bucket arrives.
    """
    state = _candle_state.setdefault(exchange_id, {}).setdefault(symbol, {})
    for interval in intervals:
        state.setdefault(interval, {})

    while True:
        trades = await exchange.watch_trades(symbol)
        for trade in trades:
            ts_ms  = trade["timestamp"]
            price  = trade["price"]
            amount = trade["amount"]

            for interval in intervals:
                buckets = state[interval]
                start = bucket_start(ts_ms, interval)

                for old_ts in [t for t in list(buckets) if t < start]:
                    c = buckets.pop(old_ts)
                    await _send_candle(
                        producer, exchange_id, symbol, interval,
                        [old_ts, c["open"], c["high"], c["low"], c["close"], c["volume"]],
                    )

                if start not in buckets:
                    buckets[start] = {
                        "open": price, "high": price,
                        "low":  price, "close": price, "volume": amount,
                    }
                else:
                    b = buckets[start]
                    b["high"]   = max(b["high"], price)
                    b["low"]    = min(b["low"],  price)
                    b["close"]  = price
                    b["volume"] += amount


def _build_streams(exchange, exchange_id: str, method: str, symbols: dict[str, list[str]], producer) -> list:
    streams = []
    multi_subscriptions = []
    for symbol, intervals in symbols.items():
        native, from_trades = _split_intervals(exchange, method, intervals)
        if method == "multi":
            multi_subscriptions += [[symbol, tf] for tf in native]
        else:
            streams += [_stream_ohlcv(exchange, exchange_id, symbol, producer, tf) for tf in native]
        if from_trades:
            streams.append(_stream_trades(exchange, exchange_id, symbol, producer, from_trades))
    if multi_subscriptions:
        streams.append(_stream_multi(exchange, exchange_id, multi_subscriptions, producer))
    return streams


async def _stream_exchange(exc_config: dict, producer: AIOKafkaProducer) -> None:
    """Streams candles from one exchange. Auto-reconnects on error."""
    exchange_id = exc_config["name"]
    symbols     = exc_config["symbols"]
    method      = exc_config["method"]

    credentials = EXCHANGE_CREDENTIALS.get(exchange_id, {})
    exchange: ccxtpro.Exchange = getattr(ccxtpro, exchange_id)(credentials)

    logger.info(f"[{exchange_id}] symbols={symbols} method={method}")

    while True:
        try:
            await exchange.load_markets()
            streams = _build_streams(
                exchange, exchange_id, method, _available_symbols(exchange, exchange_id, symbols), producer,
            )
            if not streams:
                logger.warning(f"[{exchange_id}] no streamable markets — retrying in {_NO_MARKETS_RETRY_SECONDS}s")
                await asyncio.sleep(_NO_MARKETS_RETRY_SECONDS)
                continue
            await run_all(streams)

        except Exception as e:
            kafka_reconnects_total.labels(exchange=exchange_id).inc()
            logger.warning(f"[{exchange_id}] Stream error: {e} — reconnecting in {_RECONNECT_DELAY_SECONDS}s")
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass


# ── Lifecycle: hot-reloaded streams ──────────────────────────────────────────

async def _reconcile_streams(
    running: dict[str, tuple[dict, asyncio.Task]],
    config: list[dict],
    producer: AIOKafkaProducer,
) -> dict[str, tuple[dict, asyncio.Task]]:
    """
    Brings the running exchange streams in line with `config`: stops streams
    for removed/disabled exchanges, restarts streams whose markets changed (or
    that died), starts new ones, and leaves unchanged streams untouched.
    """
    desired = {exc["name"]: exc for exc in config}
    kept: dict[str, tuple[dict, asyncio.Task]] = {}
    stopped = []

    for name, (current, task) in running.items():
        if desired.get(name) == current and not task.done():
            kept[name] = (current, task)
            continue
        reason = "removed" if name not in desired else "config changed"
        logger.info(f"[{name}] stopping stream ({reason})")
        task.cancel()
        stopped.append(task)
    await asyncio.gather(*stopped, return_exceptions=True)

    to_start = [exc for name, exc in desired.items() if name not in kept]
    if to_start:
        await _create_topics(to_start)
    for exc in to_start:
        logger.info(f"[{exc['name']}] starting stream")
        kept[exc["name"]] = (exc, asyncio.create_task(_stream_exchange(exc, producer)))
    return kept


async def run_producer() -> None:
    """
    Loads config from DB, creates topics and starts all exchange streams, then
    re-reads the config every PRODUCER_CONFIG_REFRESH_SECONDS and applies changes.
    The Kafka producer is only started once there's something to stream.
    """
    producer: AIOKafkaProducer | None = None
    fx_task: asyncio.Task | None = None
    running: dict[str, tuple[dict, asyncio.Task]] = {}

    try:
        while True:
            try:
                config = await _load_exchange_config()
            except Exception as e:
                logger.warning(f"Could not load exchange config from DB ({e}) — keeping current streams")
                config = None

            if config is not None:
                if not config and producer is None:
                    logger.warning("No enabled exchanges found in DB — producer idle")
                else:
                    if producer is None:
                        producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
                        await producer.start()
                        logger.info("Kafka producer started")
                        fx_task = asyncio.create_task(watch_fx_rates(fx_rates))
                    running = await _reconcile_streams(running, config, producer)

            if PRODUCER_CONFIG_REFRESH_SECONDS <= 0:
                # Hot reload disabled — run the streams started above until cancelled.
                await run_all(task for _, task in running.values())
                return
            await asyncio.sleep(PRODUCER_CONFIG_REFRESH_SECONDS)
    finally:
        tasks = [task for _, task in running.values()] + ([fx_task] if fx_task else [])
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if producer is not None:
            await producer.stop()
            logger.info("Kafka producer stopped")
