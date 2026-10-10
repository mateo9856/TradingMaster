from datetime import datetime, timezone

import pandas as pd
import pytest

from app.kafka.yahoo_source import YahooPoller, frame_for, poll_every, rows_to_ohlcv


def yahoo_frame(symbols: dict[str, list[tuple]], tz="America/New_York"):
    """
    A yf.download(group_by="ticker")-shaped frame: (ticker, field) columns over
    the union of every symbol's timestamps, NaN where a symbol has no bar.
    """
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    frames = {}
    for symbol, bars in symbols.items():
        index = pd.DatetimeIndex([b[0] for b in bars], tz=tz)
        rows = [[o, h, low, c, c, v] for _, o, h, low, c, v in bars]
        frames[symbol] = pd.DataFrame(rows, index=index, columns=fields)
    return pd.concat(frames, axis=1, names=["Ticker", "Price"])


BAR_1 = ("2026-10-09 10:00", 10.0, 11.0, 9.0, 10.5, 1000)
BAR_2 = ("2026-10-09 10:01", 10.5, 10.6, 10.1, 10.2, 500)


def ms(text: str, tz="America/New_York") -> int:
    return int(pd.Timestamp(text, tz=tz).tz_convert("UTC").timestamp() * 1000)


def test_rows_to_ohlcv_converts_to_utc_milliseconds():
    frame = frame_for(yahoo_frame({"AAPL": [BAR_1]}), "AAPL")

    assert rows_to_ohlcv(frame, "1m") == [[ms("2026-10-09 10:00"), 10.0, 11.0, 9.0, 10.5, 1000.0]]


def test_float_noise_is_rounded_off_prices():
    frame = yahoo_frame({"AAPL": [("2026-10-09 10:00", 331.7900085449219, 335.44000244140625,
                                   330.70001220703125, 334.8999938964844, 23373526.0)]})

    (bar,) = rows_to_ohlcv(frame_for(frame, "AAPL"), "1m")
    assert bar[1:5] == [331.79, 335.44, 330.7, 334.9]


def test_rows_without_prices_are_dropped():
    # In a mixed batch, Warsaw rows exist for New York's hours with NaN prices.
    frame = yahoo_frame({"PKN.WA": [("2026-10-09 10:00", float("nan"), float("nan"), float("nan"),
                                     float("nan"), float("nan"))]})

    assert rows_to_ohlcv(frame_for(frame, "PKN.WA"), "1m") == []


def test_daily_bars_are_keyed_at_midnight_utc_of_the_trading_date():
    frame = yahoo_frame({"PKN.WA": [("2026-10-09 00:00", 60, 61, 59, 60.5, 10)]}, tz="Europe/Warsaw")

    (bar,) = rows_to_ohlcv(frame_for(frame, "PKN.WA"), "1d")
    assert bar[0] == int(datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp() * 1000)


def test_frame_for_handles_missing_symbols_and_flat_frames():
    multi = yahoo_frame({"AAPL": [BAR_1]})
    assert frame_for(multi, "MSFT") is None
    assert frame_for(None, "AAPL") is None
    flat = multi["AAPL"]
    assert frame_for(flat, "AAPL") is flat


def test_longer_bars_are_polled_less_often():
    assert poll_every("1m", 60) == 60
    assert poll_every("5m", 60) == 300
    assert poll_every("1h", 60) == 300
    assert poll_every("1d", 60) == 300


async def test_poller_sends_new_and_changed_bars_only():
    frames = [
        yahoo_frame({"AAPL": [BAR_1], "PKN.WA": [BAR_1]}),
        yahoo_frame({"AAPL": [BAR_1, BAR_2], "PKN.WA": [BAR_1]}),                       # AAPL: one new bar
        yahoo_frame({"AAPL": [BAR_1, BAR_2[:4] + (10.3, 600)], "PKN.WA": [BAR_1]}),     # AAPL: last bar changed
    ]
    sent = []

    async def send(exchange, symbol, interval, ohlcv):
        sent.append((exchange, symbol, interval, ohlcv[4]))

    fetched = []

    def fetch(symbols, interval):
        fetched.append((sorted(symbols), interval))
        return frames.pop(0)

    poller = YahooPoller({"AAPL/USD": ["1m"], "PKN.WA/PLN": ["1m", "1d"]}, send, fetch=fetch)

    assert await poller.poll_interval("1m") == 2
    assert await poller.poll_interval("1m") == 1
    assert await poller.poll_interval("1m") == 1

    assert fetched[0] == (["AAPL", "PKN.WA"], "1m")
    assert sent == [
        ("yahoo", "AAPL/USD", "1m", 10.5),
        ("yahoo", "PKN.WA/PLN", "1m", 10.5),
        ("yahoo", "AAPL/USD", "1m", 10.2),
        ("yahoo", "AAPL/USD", "1m", 10.3),
    ]


async def test_poll_due_survives_a_failing_download_and_waits_for_the_next_turn():
    now = [0.0]
    calls = []

    def fetch(symbols, interval):
        calls.append(interval)
        raise RuntimeError("Too Many Requests")

    async def send(*args):
        pass

    poller = YahooPoller({"AAPL/USD": ["1m", "1d"]}, send, fetch=fetch, clock=lambda: now[0])

    await poller.poll_due()
    await poller.poll_due()          # nothing due yet
    now[0] = 61
    await poller.poll_due()          # only 1m is due again

    assert calls == ["1m", "1d", "1m"]
