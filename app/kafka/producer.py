"""
Exchange → Kafka producer

Uses CCXT Pro to stream live OHLCV candles from multiple exchanges
simultaneously, then publishes each candle to a Kafka topic.

Topic naming convention:  {exchange}.{ticker_normalized}.candles
Example:                  binance.BTCUSDT.candles
"""

import asyncio
import json
import logging
from datetime import datetime

import ccxt.pro as ccxtpro
from aiokafka import AIOKafkaProducer

from app.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    WATCH_SYMBOLS,
    WATCH_EXCHANGES,
    EXCHANGE_CREDENTIALS,
)

logger = logging.getLogger(__name__)

# Symbols available per exchange — not all symbols exist on all exchanges
EXCHANGE_SYMBOLS: dict = {
    "binance":  ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
    "kraken":   ["BTC/USDT", "ETH/USDT"],           # no BNB on Kraken
    "coinbase": ["BTC/USDT", "ETH/USDT"],           # no BNB on Coinbase
}


def _topic_name(exchange: str, symbol: str) -> str:
    """BTC/USDT → BTCUSDT, topic → binance.BTCUSDT.candles"""
    normalized = symbol.replace("/", "")
    return f"{exchange}.{normalized}.candles"


async def _send_candle(
    producer: AIOKafkaProducer,
    exchange_id: str,
    symbol: str,
    interval: str,
    ohlcv: list,
) -> None:
    """Serialize one OHLCV candle and send to Kafka."""
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
    await producer.send(
        topic,
        value=json.dumps(payload).encode("utf-8"),
    )
    logger.debug(f"[{exchange_id}] Sent {symbol} candle to {topic}")


async def _stream_with_multi(
    exchange: ccxtpro.Exchange,
    exchange_id: str,
    symbols: list[str],
    producer: AIOKafkaProducer,
    interval: str = "1m",
) -> None:
    """
    Stream using watchOHLCVForSymbols — supported by Binance.
    Returns: {symbol: {timeframe: [[ts, o, h, l, c, v], ...]}}
    """
    while True:
        candles = await exchange.watch_ohlcv_for_symbols(
            [[symbol, interval] for symbol in symbols]
        )
        for symbol, timeframes in candles.items():
            for tf, ohlcv_list in timeframes.items():
                for ohlcv in ohlcv_list:
                    await _send_candle(producer, exchange_id, symbol, tf, ohlcv)


async def _stream_per_symbol(
    exchange: ccxtpro.Exchange,
    exchange_id: str,
    symbol: str,
    producer: AIOKafkaProducer,
    interval: str = "1m",
) -> None:
    """
    Stream using watchOHLCV per symbol — fallback for Kraken, Coinbase etc.
    Returns: [[ts, o, h, l, c, v], ...]
    """
    while True:
        ohlcv_list = await exchange.watch_ohlcv(symbol, interval)
        for ohlcv in ohlcv_list:
            await _send_candle(producer, exchange_id, symbol, interval, ohlcv)


async def _stream_exchange(
    exchange_id: str,
    symbols: list[str],
    producer: AIOKafkaProducer,
    interval: str = "1m",
) -> None:
    """
    Opens a CCXT Pro WebSocket connection to one exchange.
    Automatically picks the right streaming method based on exchange support.
    Reconnects automatically on any error.
    """
    credentials = EXCHANGE_CREDENTIALS.get(exchange_id, {})
    exchange: ccxtpro.Exchange = getattr(ccxtpro, exchange_id)(credentials)

    # Use only symbols available on this exchange
    available = EXCHANGE_SYMBOLS.get(exchange_id, symbols)
    active_symbols = [s for s in symbols if s in available]

    if not active_symbols:
        logger.warning(f"[{exchange_id}] No valid symbols — skipping")
        return

    logger.info(f"[{exchange_id}] Starting stream for {active_symbols}")

    while True:
        try:
            await exchange.load_markets()
            supports_multi = exchange.has.get("watchOHLCVForSymbols", False)

            if supports_multi:
                logger.info(f"[{exchange_id}] Using watchOHLCVForSymbols")
                await _stream_with_multi(exchange, exchange_id, active_symbols, producer, interval)
            else:
                logger.info(f"[{exchange_id}] Using watchOHLCV per symbol")
                # Run one coroutine per symbol concurrently
                await asyncio.gather(*[
                    _stream_per_symbol(exchange, exchange_id, symbol, producer, interval)
                    for symbol in active_symbols
                ])

        except Exception as e:
            logger.warning(f"[{exchange_id}] Stream error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)

        finally:
            try:
                await exchange.close()
            except Exception:
                pass


async def run_producer() -> None:
    """
    Entry point — starts one streaming task per exchange,
    all sharing the same Kafka producer connection.
    """
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    logger.info("Kafka producer started")

    try:
        await asyncio.gather(*[
            _stream_exchange(exchange_id, WATCH_SYMBOLS, producer)
            for exchange_id in WATCH_EXCHANGES
        ])
    finally:
        await producer.stop()
        logger.info("Kafka producer stopped")