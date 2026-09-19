import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.kafka import producer as producer_module
from app.kafka.producer import (
    _build_streams,
    _build_topic_list,
    _create_topics,
    _group_symbols,
    _load_exchange_config,
    _reconcile_streams,
    _send_candle,
    _split_intervals,
    _stream_exchange,
    _stream_multi,
    _stream_ohlcv,
    _stream_trades,
    build_unified_payload,
    run_producer,
)


def session_returning(rows):
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def exchange_mock(markets=("BTC/USDT",), timeframes=("1m", "5m", "1h", "1d")):
    exchange = AsyncMock()
    exchange.markets = {m: {} for m in markets}
    exchange.timeframes = {tf: tf for tf in timeframes}
    return exchange


# ── Topics ───────────────────────────────────────────────────────────────────

def test_topic_names_use_the_unified_ticker():
    assert producer_module._topic_name("binance", "BTC/USDT") == "binance.BTCUSD.candles"
    assert producer_module._topic_name("coinbase", "BTC/USD") == "coinbase.BTCUSD.candles"
    assert "/" not in producer_module._topic_name("kraken", "ETH/USDT")


async def test_build_topic_list_uses_database_configuration():
    config = [
        {"name": "binance", "symbols": {"BTC/USDT": ["1m"], "ETH/USDT": ["1m", "5m"]}},
        {"name": "coinbase", "symbols": {"BTC/USD": ["30s"]}},
    ]

    assert await _build_topic_list(config) == [
        "binance.BTCUSD.candles",
        "binance.ETHUSD.candles",
        "coinbase.BTCUSD.candles",
    ]


async def test_create_topics_creates_one_topic_per_symbol():
    admin = AsyncMock()
    config = [{"name": "binance", "symbols": {"BTC/USDT": ["1m"]}}]

    with patch.object(producer_module, "AIOKafkaAdminClient", return_value=admin):
        await _create_topics(config)

    admin.start.assert_awaited_once()
    admin.create_topics.assert_awaited_once()
    assert admin.create_topics.call_args.args[0][0].name == "binance.BTCUSD.candles"
    admin.close.assert_awaited_once()


async def test_create_topics_survives_kafka_errors():
    admin = AsyncMock()
    admin.create_topics.side_effect = RuntimeError("broker unavailable")

    with patch.object(producer_module, "AIOKafkaAdminClient", return_value=admin):
        await _create_topics([{"name": "binance", "symbols": {"BTC/USDT": ["1m"]}}])

    admin.close.assert_awaited_once()


async def test_create_topics_skips_kafka_when_nothing_to_create():
    with patch.object(producer_module, "AIOKafkaAdminClient") as admin:
        await _create_topics([])

    admin.assert_not_called()


# ── Config from the database ─────────────────────────────────────────────────

async def test_load_exchange_config_groups_intervals_per_ticker():
    rows = [
        ("binance", "multi", "BTC/USDT", "1m"),
        ("binance", "multi", "BTC/USDT", "30s"),
        ("binance", "multi", "ETH/USDT", "1h"),
        ("coinbase", "trades", "BTC/USD", "1d"),
    ]

    with patch.object(producer_module, "AsyncSessionLocal", return_value=session_returning(rows)):
        config = await _load_exchange_config()

    assert config == [
        {"name": "binance", "method": "multi", "symbols": {"BTC/USDT": ["30s", "1m"], "ETH/USDT": ["1h"]}},
        {"name": "coinbase", "method": "trades", "symbols": {"BTC/USD": ["1d"]}},
    ]


async def test_load_exchange_config_skips_exchanges_without_valid_symbols():
    rows = [("kraken", "ohlcv", "ETH/BTC", "1m")]

    with patch.object(producer_module, "AsyncSessionLocal", return_value=session_returning(rows)):
        assert await _load_exchange_config() == []


async def test_load_exchange_config_propagates_db_errors():
    context = MagicMock()
    context.__aenter__ = AsyncMock(side_effect=OSError("db down"))
    context.__aexit__ = AsyncMock(return_value=None)

    with patch.object(producer_module, "AsyncSessionLocal", return_value=context):
        with pytest.raises(OSError):
            await _load_exchange_config()


def test_group_symbols_drops_unsupported_intervals_and_quotes():
    rows = [("BTC/USDT", "1m"), ("BTC/USDT", "15m"), ("ETH/BTC", "1m"), ("BTC/USDT", "1m")]

    assert _group_symbols("binance", rows) == {"BTC/USDT": ["1m"]}


def test_group_symbols_keeps_one_market_per_unified_ticker_preferring_usd():
    rows = [("BTC/USDT", "1m"), ("BTC/USDC", "1m"), ("BTC/USD", "5m"), ("ETH/USDC", "1m"), ("ETH/USDT", "1m")]

    assert _group_symbols("kraken", rows) == {"BTC/USD": ["5m"], "ETH/USDT": ["1m"]}


# ── Unified message format ───────────────────────────────────────────────────

def test_unified_payload_converts_usdt_prices_to_usd_decimal_strings():
    payload = build_unified_payload(
        "binance", "BTC/USDT", "1m",
        [1_700_000_000_000, 65000.1, 65100, 64900.5, 65050.25, 1.5], Decimal("0.9998"),
    )

    assert payload == {
        "schema_version": 2,
        "exchange": "binance",
        "ticker": "BTC/USD",
        "source_ticker": "BTC/USDT",
        "quote_currency": "USD",
        "fx_rate": "0.99980000",
        "interval": "1m",
        "timestamp": "2023-11-14T22:13:20",
        "open_price": "64987.09998000",
        "high_price": "65086.98000000",
        "low_price": "64887.51990000",
        "close_price": "65037.23995000",
        "volume": "1.50000000",
    }


def test_unified_payload_keeps_usd_prices_unchanged():
    payload = build_unified_payload("coinbase", "ETH/USD", "30s", [30_000, 3500, 3510, 3490, 3505.5, 2], 1)

    assert payload["ticker"] == "ETH/USD"
    assert payload["close_price"] == "3505.50000000"
    assert payload["fx_rate"] == "1.00000000"


def test_unified_payload_has_identical_shape_for_every_exchange():
    ohlcv = [60_000, 1, 2, 0.5, 1.5, 3]
    payloads = [
        build_unified_payload("binance", "BTC/USDT", "1m", ohlcv, "0.9998"),
        build_unified_payload("kraken", "BTC/USD", "1m", ohlcv, 1),
        build_unified_payload("coinbase", "BTC/USDC", "1m", ohlcv, "1.0001"),
    ]

    assert all(p.keys() == payloads[0].keys() for p in payloads)
    assert {p["ticker"] for p in payloads} == {"BTC/USD"}
    assert all(len(p["close_price"].split(".")[1]) == 8 for p in payloads)


@pytest.mark.parametrize("ohlcv", [
    [None, 1, 2, 0.5, 1.5, 3],
    [60_000, None, 2, 0.5, 1.5, 3],
    [60_000, 1, 2, 0.5, 1.5, -3],
    [60_000, 1, 2, 0.5],
    None,
])
def test_unified_payload_rejects_invalid_ohlcv(ohlcv):
    with pytest.raises(ValueError):
        build_unified_payload("binance", "BTC/USDT", "1m", ohlcv, 1)


@pytest.mark.parametrize("rate", [0, -1, None, "abc"])
def test_unified_payload_rejects_invalid_fx_rate(rate):
    with pytest.raises(ValueError):
        build_unified_payload("binance", "BTC/USDT", "1m", [60_000, 1, 2, 0.5, 1.5, 3], rate)


async def test_send_candle_publishes_unified_payload_to_unified_topic():
    kafka = AsyncMock()

    with patch.object(producer_module.fx_rates, "get", return_value=(Decimal("0.9998"), "live")) as get:
        await _send_candle(kafka, "binance", "BTC/USDT", "1m", [1_700_000_000_000, 1, 2, 0.5, 1.5, 3])

    get.assert_called_once_with("USDT")
    topic, = kafka.send.call_args.args
    payload = json.loads(kafka.send.call_args.kwargs["value"])
    assert topic == "binance.BTCUSD.candles"
    assert payload["ticker"] == "BTC/USD"
    assert payload["source_ticker"] == "BTC/USDT"
    assert payload["close_price"] == "1.49970000"
    assert payload["interval"] == "1m"


async def test_send_candle_drops_invalid_candle_without_raising():
    kafka = AsyncMock()

    await _send_candle(kafka, "binance", "BTC/USDT", "1m", [1, None, 2, 0.5, 1.5, 3])

    kafka.send.assert_not_awaited()


# ── Intervals: native vs built from trades ───────────────────────────────────

def test_split_intervals_uses_native_timeframes_and_trades_for_the_rest():
    exchange = exchange_mock(timeframes=("1m", "5m", "1h", "1d"))

    assert _split_intervals(exchange, "multi", ["30s", "1m", "5m", "1h", "1d"]) == (
        ["1m", "5m", "1h", "1d"], ["30s"],
    )


def test_split_intervals_trade_method_builds_every_interval_from_trades():
    exchange = exchange_mock(timeframes=("1m", "5m"))

    assert _split_intervals(exchange, "trades", ["30s", "1m"]) == ([], ["30s", "1m"])


def test_split_intervals_without_timeframes_falls_back_to_trades():
    exchange = exchange_mock(timeframes=())

    assert _split_intervals(exchange, "ohlcv", ["1m"]) == ([], ["1m"])


def test_build_streams_multi_subscribes_every_native_pair_in_one_stream():
    exchange = exchange_mock(markets=("BTC/USDT", "ETH/USDT"))

    with (
        patch.object(producer_module, "_stream_multi", new=MagicMock(return_value="multi")) as multi,
        patch.object(producer_module, "_stream_trades", new=MagicMock(return_value="trades")) as trades,
    ):
        streams = _build_streams(
            exchange, "binance", "multi", {"BTC/USDT": ["30s", "1m", "5m"], "ETH/USDT": ["1h"]}, "kafka",
        )

    assert streams == ["trades", "multi"]
    multi.assert_called_once_with(
        exchange, "binance", [["BTC/USDT", "1m"], ["BTC/USDT", "5m"], ["ETH/USDT", "1h"]], "kafka",
    )
    trades.assert_called_once_with(exchange, "binance", "BTC/USDT", "kafka", ["30s"])


def test_build_streams_ohlcv_runs_one_stream_per_symbol_and_interval():
    exchange = exchange_mock()

    with patch.object(producer_module, "_stream_ohlcv", new=MagicMock(side_effect=lambda *a: a[-1])):
        streams = _build_streams(exchange, "kraken", "ohlcv", {"BTC/USDT": ["1m", "1d"]}, "kafka")

    assert streams == ["1m", "1d"]


async def test_stream_multi_forwards_all_timeframes():
    exchange = AsyncMock()
    exchange.watch_ohlcv_for_symbols.side_effect = [
        {"BTC/USDT": {"1m": [[1, 1, 2, 0, 1.5, 3]], "5m": [[2, 1, 2, 0, 1.5, 9]]}},
        asyncio.CancelledError(),
    ]
    kafka = AsyncMock()

    with patch.object(producer_module, "_send_candle", new_callable=AsyncMock) as send:
        with pytest.raises(asyncio.CancelledError):
            await _stream_multi(exchange, "binance", [["BTC/USDT", "1m"], ["BTC/USDT", "5m"]], kafka)

    exchange.watch_ohlcv_for_symbols.assert_awaited_with([["BTC/USDT", "1m"], ["BTC/USDT", "5m"]])
    assert send.await_args_list[0].args == (kafka, "binance", "BTC/USDT", "1m", [1, 1, 2, 0, 1.5, 3])
    assert send.await_args_list[1].args == (kafka, "binance", "BTC/USDT", "5m", [2, 1, 2, 0, 1.5, 9])


async def test_stream_ohlcv_forwards_each_candle():
    exchange = AsyncMock()
    exchange.watch_ohlcv.side_effect = [
        [[1, 10, 12, 9, 11, 5]],
        asyncio.CancelledError(),
    ]
    kafka = AsyncMock()

    with patch.object(producer_module, "_send_candle", new_callable=AsyncMock) as send:
        with pytest.raises(asyncio.CancelledError):
            await _stream_ohlcv(exchange, "kraken", "BTC/USDT", kafka, "1h")

    exchange.watch_ohlcv.assert_awaited_with("BTC/USDT", "1h")
    send.assert_awaited_once_with(kafka, "kraken", "BTC/USDT", "1h", [1, 10, 12, 9, 11, 5])


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
        with pytest.raises(asyncio.CancelledError):
            await _stream_trades(exchange, "coinbase", "BTC/USD", kafka, ["1m"])

    send.assert_awaited_once_with(kafka, "coinbase", "BTC/USD", "1m", [60_000, 10, 12, 10, 12, 5])


async def test_stream_trades_builds_30s_and_1m_candles_from_one_feed():
    producer_module._candle_state.clear()
    exchange = AsyncMock()
    exchange.watch_trades.side_effect = [
        [
            {"timestamp": 60_000, "price": 10, "amount": 1},   # 30s bucket 60_000, 1m bucket 60_000
            {"timestamp": 95_000, "price": 14, "amount": 2},   # 30s bucket 90_000 → flushes 60_000
            {"timestamp": 125_000, "price": 9, "amount": 4},   # 30s 120_000 + 1m 120_000 → flush both
        ],
        asyncio.CancelledError(),
    ]
    kafka = AsyncMock()

    with patch.object(producer_module, "_send_candle", new_callable=AsyncMock) as send:
        with pytest.raises(asyncio.CancelledError):
            await _stream_trades(exchange, "binance", "BTC/USDT", kafka, ["30s", "1m"])

    sent = [(c.args[3], c.args[4]) for c in send.await_args_list]
    assert sent == [
        ("30s", [60_000, 10, 10, 10, 10, 1]),
        ("30s", [90_000, 14, 14, 14, 14, 2]),
        ("1m", [60_000, 10, 14, 10, 14, 3]),
    ]


# ── Exchange stream lifecycle ────────────────────────────────────────────────

async def test_stream_exchange_dispatches_method_and_closes_on_cancellation():
    config = {"name": "binance", "symbols": {"BTC/USDT": ["1m"]}, "method": "multi"}
    exchange = exchange_mock()

    with (
        patch.object(producer_module, "ccxtpro") as ccxt,
        patch.object(producer_module, "_stream_multi", new_callable=AsyncMock) as stream,
    ):
        ccxt.binance.return_value = exchange
        stream.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await _stream_exchange(config, AsyncMock())

    exchange.load_markets.assert_awaited_once()
    stream.assert_awaited_once()
    assert stream.await_args.args[2] == [["BTC/USDT", "1m"]]
    exchange.close.assert_awaited_once()


async def test_stream_exchange_skips_markets_the_exchange_does_not_list():
    config = {"name": "binance", "symbols": {"BTC/USDT": ["1m"], "FAKE/USDT": ["1m"]}, "method": "multi"}
    exchange = exchange_mock(markets=("BTC/USDT",))

    with (
        patch.object(producer_module, "ccxtpro") as ccxt,
        patch.object(producer_module, "_stream_multi", new_callable=AsyncMock) as stream,
    ):
        ccxt.binance.return_value = exchange
        stream.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await _stream_exchange(config, AsyncMock())

    assert stream.await_args.args[2] == [["BTC/USDT", "1m"]]


async def test_stream_exchange_reconnects_after_stream_error():
    config = {"name": "kraken", "symbols": {"BTC/USD": ["1m"]}, "method": "ohlcv"}
    exchange = exchange_mock(markets=("BTC/USD",))

    with (
        patch.object(producer_module, "ccxtpro") as ccxt,
        patch.object(producer_module, "_stream_ohlcv", new_callable=AsyncMock) as stream,
        patch.object(producer_module.asyncio, "sleep", new_callable=AsyncMock) as sleep,
    ):
        ccxt.kraken.return_value = exchange
        stream.side_effect = [RuntimeError("socket closed"), asyncio.CancelledError()]
        with pytest.raises(asyncio.CancelledError):
            await _stream_exchange(config, AsyncMock())

    sleep.assert_awaited_once_with(5)
    assert exchange.load_markets.await_count == 2
    assert exchange.close.await_count == 2


async def test_stream_exchange_waits_when_no_market_is_streamable():
    config = {"name": "binance", "symbols": {"FAKE/USDT": ["1m"]}, "method": "multi"}
    exchange = exchange_mock(markets=())

    with (
        patch.object(producer_module, "ccxtpro") as ccxt,
        patch.object(producer_module.asyncio, "sleep", new_callable=AsyncMock) as sleep,
    ):
        ccxt.binance.return_value = exchange
        sleep.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await _stream_exchange(config, AsyncMock())

    sleep.assert_awaited_once_with(producer_module._NO_MARKETS_RETRY_SECONDS)


# ── Hot reload ───────────────────────────────────────────────────────────────

BINANCE = {"name": "binance", "method": "multi", "symbols": {"BTC/USDT": ["1m"]}}
KRAKEN = {"name": "kraken", "method": "ohlcv", "symbols": {"BTC/USD": ["1m"]}}


async def _forever(*_):
    await asyncio.Event().wait()


async def test_reconcile_starts_streams_for_new_exchanges():
    with (
        patch.object(producer_module, "_stream_exchange", side_effect=_forever) as stream,
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock) as topics,
    ):
        running = await _reconcile_streams({}, [BINANCE, KRAKEN], "kafka")
        await asyncio.sleep(0)

    assert set(running) == {"binance", "kraken"}
    topics.assert_awaited_once_with([BINANCE, KRAKEN])
    assert stream.call_count == 2
    for _, task in running.values():
        task.cancel()


async def test_reconcile_leaves_unchanged_streams_running():
    task = asyncio.create_task(_forever())

    with (
        patch.object(producer_module, "_stream_exchange") as stream,
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock) as topics,
    ):
        running = await _reconcile_streams({"binance": (dict(BINANCE), task)}, [BINANCE], "kafka")

    assert running["binance"][1] is task
    assert not task.cancelled()
    stream.assert_not_called()
    topics.assert_not_awaited()
    task.cancel()


async def test_reconcile_stops_removed_or_disabled_exchanges():
    task = asyncio.create_task(_forever())

    with patch.object(producer_module, "_create_topics", new_callable=AsyncMock):
        running = await _reconcile_streams({"binance": (BINANCE, task)}, [], "kafka")

    assert running == {}
    assert task.cancelled()


async def test_reconcile_restarts_exchange_whose_markets_changed():
    old_task = asyncio.create_task(_forever())
    changed = {**BINANCE, "symbols": {"BTC/USDT": ["1m"], "SOL/USDT": ["30s", "1m"]}}

    with (
        patch.object(producer_module, "_stream_exchange", side_effect=_forever) as stream,
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock) as topics,
    ):
        running = await _reconcile_streams({"binance": (BINANCE, old_task)}, [changed], "kafka")
        await asyncio.sleep(0)

    assert old_task.cancelled()
    assert running["binance"][0] == changed
    assert running["binance"][1] is not old_task
    topics.assert_awaited_once_with([changed])
    stream.assert_called_once_with(changed, "kafka")
    running["binance"][1].cancel()


async def test_reconcile_restarts_a_stream_that_died():
    dead = asyncio.create_task(asyncio.sleep(0))
    await dead

    with (
        patch.object(producer_module, "_stream_exchange", side_effect=_forever),
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock),
    ):
        running = await _reconcile_streams({"binance": (BINANCE, dead)}, [BINANCE], "kafka")

    assert running["binance"][1] is not dead
    running["binance"][1].cancel()


def _stop_after(iterations: int):
    calls = {"n": 0}

    async def sleep(_seconds):
        calls["n"] += 1
        if calls["n"] >= iterations:
            raise asyncio.CancelledError()

    return sleep


async def test_run_producer_loads_config_starts_and_stops_kafka():
    kafka = AsyncMock()

    with (
        patch.object(producer_module, "_load_exchange_config", new_callable=AsyncMock, return_value=[BINANCE]),
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock) as topics,
        patch.object(producer_module, "AIOKafkaProducer", return_value=kafka),
        patch.object(producer_module, "_stream_exchange", side_effect=_forever),
        patch.object(producer_module, "watch_fx_rates", side_effect=_forever) as fx,
        patch.object(producer_module.asyncio, "sleep", side_effect=_stop_after(1)),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_producer()

    topics.assert_awaited_once_with([BINANCE])
    fx.assert_called_once()
    kafka.start.assert_awaited_once()
    kafka.stop.assert_awaited_once()


async def test_run_producer_refreshes_config_on_interval():
    kafka = AsyncMock()
    load = AsyncMock(side_effect=[[BINANCE], [BINANCE, KRAKEN]])

    with (
        patch.object(producer_module, "_load_exchange_config", load),
        patch.object(producer_module, "_reconcile_streams", new_callable=AsyncMock, return_value={}) as reconcile,
        patch.object(producer_module, "AIOKafkaProducer", return_value=kafka),
        patch.object(producer_module, "watch_fx_rates", side_effect=_forever),
        patch.object(producer_module, "PRODUCER_CONFIG_REFRESH_SECONDS", 15),
        patch.object(producer_module.asyncio, "sleep", side_effect=_stop_after(2)) as sleep,
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_producer()

    assert load.await_count == 2
    assert [c.args[1] for c in reconcile.await_args_list] == [[BINANCE], [BINANCE, KRAKEN]]
    sleep.assert_called_with(15)
    kafka.start.assert_awaited_once()


async def test_run_producer_keeps_streams_when_config_reload_fails():
    load = AsyncMock(side_effect=[[BINANCE], OSError("db down")])

    with (
        patch.object(producer_module, "_load_exchange_config", load),
        patch.object(producer_module, "_reconcile_streams", new_callable=AsyncMock, return_value={}) as reconcile,
        patch.object(producer_module, "AIOKafkaProducer", return_value=AsyncMock()),
        patch.object(producer_module, "watch_fx_rates", side_effect=_forever),
        patch.object(producer_module.asyncio, "sleep", side_effect=_stop_after(2)),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_producer()

    # Only the successful load was applied — the failed reload changed nothing.
    reconcile.assert_awaited_once()


async def test_run_producer_stays_idle_without_enabled_exchanges_but_keeps_polling():
    load = AsyncMock(return_value=[])

    with (
        patch.object(producer_module, "_load_exchange_config", load),
        patch.object(producer_module, "AIOKafkaProducer") as kafka,
        patch.object(producer_module.asyncio, "sleep", side_effect=_stop_after(3)),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_producer()

    kafka.assert_not_called()
    assert load.await_count == 3


async def test_run_producer_without_refresh_runs_streams_until_they_finish():
    kafka = AsyncMock()

    with (
        patch.object(producer_module, "_load_exchange_config", new_callable=AsyncMock, return_value=[BINANCE]),
        patch.object(producer_module, "_create_topics", new_callable=AsyncMock),
        patch.object(producer_module, "AIOKafkaProducer", return_value=kafka),
        patch.object(producer_module, "_stream_exchange", new_callable=AsyncMock) as stream,
        patch.object(producer_module, "watch_fx_rates", side_effect=_forever),
        patch.object(producer_module, "PRODUCER_CONFIG_REFRESH_SECONDS", 0),
        patch.object(producer_module.asyncio, "sleep", new_callable=AsyncMock) as sleep,
    ):
        await run_producer()

    stream.assert_awaited_once()
    sleep.assert_not_awaited()
    kafka.stop.assert_awaited_once()
