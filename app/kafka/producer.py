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


def _topic_name(exchange: str, symbol: str) -> str:
    """btc/usdt → BTCUSDT, topic → binance.BTCUSDT.candles"""
    normalized = symbol.replace("/", "")
    return f"{exchange}.{normalized}.candles"


async def _stream_exchange(
    exchange_id: str,
    symbols: list[str],
    producer: AIOKafkaProducer,
    interval: str = "1m",
) -> None:
    """
    Opens a CCXT Pro WebSocket connection to one exchange and
    forwards every completed candle to Kafka.
    Reconnects automatically on any error.
    """
    credentials = EXCHANGE_CREDENTIALS.get(exchange_id, {})
    exchange: ccxtpro.Exchange = getattr(ccxtpro, exchange_id)(credentials)

    logger.info(f"[{exchange_id}] Starting stream for {symbols}")

    while True:  # auto-reconnect loop
        try:
            while True:
                candles = await exchange.watch_ohlcv_for_symbols(
                    [[symbol, interval] for symbol in symbols]
                )

                for symbol, ohlcv_list in candles.items():
                    for ohlcv in ohlcv_list:
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

        except Exception as e:
            logger.warning(f"[{exchange_id}] Stream error: {e} — reconnecting in 5s")
            await asyncio.sleep(5)

        finally:
            try:
                await exchange.close()
            except Exception:
                pass


async def run_producer() -> None:
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()
    logger.info("Kafka producer started")

    try:
        await asyncio.gather(
            *[
                _stream_exchange(exchange_id, WATCH_SYMBOLS, producer)
                for exchange_id in WATCH_EXCHANGES
            ]
        )
    finally:
        await producer.stop()
        logger.info("Kafka producer stopped")