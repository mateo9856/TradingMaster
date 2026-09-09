import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.kafka import producer as producer_module
from app.kafka.producer import (
    _build_topic_list,
    _create_topics,
    _load_exchange_config,
    _send_candle,
    _stream_exchange,
    _stream_multi,
    _stream_ohlcv,
    _stream_trades,
    run_producer,
)


def test_topic_names_remove_symbol_separator():
    assert producer_module._topic_name("binance", "BTC/USDT") == "binance.BTCUSDT.candles"
    assert "/" not in producer_module._topic_name("kraken", "ETH/USDT")


async def test_load_exchange_config_reads_only_enabled_rows():
    exchange = MagicMock(id=4, method="multi", enabled=True)
    exchange.name = "binance"
    symbol = MagicMock(ticker="BTC/USDT", interval="5m", enabled=True)
    session = AsyncMock()
    exchange_result = MagicMock()
    exchange_result.scalars.return_value.all.return_value = [exchange]
    symbol_result = MagicMock()
    symbol_result.scalars.return_value.all.return_value = [symbol]
    session.execute.side_effect = [exchange_result, symbol_result]
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)

    with patch.object(producer_module, "AsyncSessionLocal", return_value=context):
        config = await _load_exchange_config()

    assert config == [{
        "name": "binance", "method": "multi",
        "symbols": ["BTC/USDT"], "interval": "5m",
    }]


async def test_build_topic_list_uses_database_configuration():
    config = [
        {"name": "binance", "symbols": ["BTC/USDT", "ETH/USDT"]},
        {"name": "coinbase", "symbols": ["BTC/USD"]},
    ]

    assert await _build_topic_list(config) == [
        "binance.BTCUSDT.candles",
        "binance.ETHUSDT.candles",
        "coinbase.BTCUSD.candles",
    ]


async def test_create_topics_creates_one_topic_per_symbol():
    admin = AsyncMock()
    config = [{"name": "binance", "symbols": ["BTC/USDT"]}]

    with patch.object(producer_module, "AIOKafkaAdminClient", return_value=admin):
        await _create_topics(config)

    admin.start.assert_awaited_once()
    admin.create_topics.assert_awaited_once()
    assert admin.create_topics.call_args.args[0][0].name == "binance.BTCUSDT.candles"
    admin.close.assert_awaited_once()


async def test_send_candle_serializes_payload_and_topic():
    kafka = AsyncMock()

    await _send_candle(kafka, "binance", "BTC/USDT", "1m", [1_700_000_000_000, 1, 2, 0.5, 1.5, 3])

    topic, = kafka.send.call_args.args
    payload = json.loads(kafka.send.call_args.kwargs["value"])
    assert topic == "binance.BTCUSDT.candles"
    assert payload["ticker"] == "BTC/USDT"
    assert payload["close_price"] == 1.5
    assert payload["interval"] == "1m"


async def test_stream_multi_forwards_all_timeframes():
    exchange = AsyncMock()
    exchange.watch_ohlcv_for_symbols.side_effect = [
        {"BTC/USDT": {"1m": [[1, 1, 2, 0, 1.5, 3]]}},
        asyncio.CancelledError(),
    ]
    kafka = AsyncMock()

    with patch.object(producer_module, "_send_candle", new_callable=AsyncMock) as send:
        try:
            await _stream_multi(exchange, "binance", ["BTC/USDT"], kafka, "1m")
        except asyncio.CancelledError:
            pass

    send.assert_awaited_once_with(kafka, "binance", "BTC/USDT", "1m", [1, 1, 2, 0, 1.5, 3])


async def test_stream_ohlcv_forwards_each_candle():
    exchange = AsyncMock()
    exchange.watch_ohlcv.side_effect = [
        [[1, 10, 12, 9, 11, 5]],
        asyncio.CancelledError(),
    ]
    kafka = AsyncMock()

    with patch.object(producer_module, "_send_candle", new_callable=AsyncMock) as send:
        try:
            await _stream_ohlcv(exchange, "kraken", "BTC/USDT", kafka, "1m")
        except asyncio.CancelledError:
            pass

    send.assert_awaited_once_with(kafka, "kraken", "BTC/USDT", "1m", [1, 10, 12, 9, 11, 5])


async def test_stream_trades_aggregates_and_flushes_completed_minute():
    producer_module._candle_state.clear()
    exchange = AsyncMock()
    exchange.watch_trades.side_effect = [
        [
            {"timestamp": 60_001, "price": 10, "amount": 2},
            {"timestamp": 60_500, "price": 12, "amount": 3},
            {"timestamp": 120_001, "price": 11, "amount": 1},
        ],
        asyncio.CancelledError(),
    ]
    kafka = AsyncMock()

    with patch.object(producer_module, "_send_candle", new_callable=AsyncMock) as send:
        try:
            await _stream_trades(exchange, "coinbase", "BTC/USD", kafka, "1m")
        except asyncio.CancelledError:
            pass

    send.assert_awaited_once_with(kafka, "coinbase", "BTC/USD", "1m", [60_000, 10, 12, 10, 12, 5])


async def test_stream_exchange_dispatches_method_and_closes_on_cancellation():
    config = {"name": "binance", "symbols": ["BTC/USDT"], "interval": "1m", "method": "multi"}
    exchange = AsyncMock()
    exchange.load_markets = AsyncMock()
    exchange.close = AsyncMock()

    with (
        patch.object(producer_module, "ccxtpro") as ccxt,
        patch.object(producer_module, "_stream_multi", new_callable=AsyncMock) as stream,
    ):
        ccxt.binance.return_value = exchange
        stream.side_effect = asyncio.CancelledError()
        try:
            await _stream_exchange(config, AsyncMock())
        except asyncio.CancelledError:
            pass

    exchange.load_markets.assert_awaited_once()
    stream.assert_awaited_once()
    exchange.close.assert_awaited_once()


async def test_run_producer_loads_config_starts_and_stops_kafka():
    config = [{"name": "binance", "symbols": ["BTC/USDT"], "interval": "1m", "method": "multi"}]
    kafka = AsyncMock()

    with (
        patch.object(producer_module, "_load_exchange_config", new_callable=AsyncMock, return_value=config),
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock) as topics,
        patch.object(producer_module, "AIOKafkaProducer", return_value=kafka),
        patch.object(producer_module, "_stream_exchange", new_callable=AsyncMock),
    ):
        await run_producer()

    topics.assert_awaited_once_with(config)
    kafka.start.assert_awaited_once()
    kafka.stop.assert_awaited_once()


async def test_run_producer_stays_idle_without_enabled_exchanges():
    with (
        patch.object(producer_module, "_load_exchange_config", new_callable=AsyncMock, return_value=[]),
        patch.object(producer_module, "AIOKafkaProducer") as kafka,
    ):
        await run_producer()

    kafka.assert_not_called()
