from datetime import date, datetime, timedelta
from math import exp

import pytest

from app.monitoring.calendar import daily_complete, market_open, sessions
from app.monitoring.forecast import estimate, forecast


def series(n=900):
    start = date(2020, 1, 1)
    return [(start+timedelta(days=i), 100*exp(i*0.001)) for i in range(n)]


@pytest.mark.parametrize('horizon', [1, 365])
def test_forecast_horizons_and_intervals(horizon):
    result = forecast(series(), horizon)
    assert result['status'] == 'ready'
    assert result['validation']['mae'] < result['validation']['baseline_mae']
    assert float(result['lower']) <= float(result['price']) <= float(result['upper'])
    assert result['target_date'] == (series()[-1][0]+timedelta(days=horizon)).isoformat()


def test_missing_invalid_and_unvalidated_history():
    assert forecast(series(364), 1)['status'] == 'insufficient_history'
    assert forecast(series(500), 365)['status'] == 'insufficient_history'
    rows = series()
    assert forecast(rows[:100]+rows[101:], 1)['status'] == 'incomplete_history'
    rows[-1] = (rows[-1][0], 0)
    assert forecast(rows, 1)['status'] == 'invalid_history'
    constant = [(day, 100) for day, _ in series()]
    assert forecast(constant, 1)['status'] == 'not_validated'


def test_backtests_use_only_past_training_data(monkeypatch):
    from app.monitoring import forecast as module
    original = module.estimate
    seen = []
    def spy(prices, steps):
        seen.append((prices[0], prices[-1], len(prices), steps))
        return original(prices, steps)
    monkeypatch.setattr(module, 'estimate', spy)
    rows = series()
    result = module.forecast(rows, 365)
    assert result['status'] == 'ready'
    for _, last, count, steps in seen[:-1]:
        assert count == 365
        assert last <= rows[-366][1]
        assert steps == 365


def test_calendar_holidays_closures_and_completed_daily():
    assert not market_open(datetime(2026, 12, 25, 16), 'NYSE')
    assert not market_open(datetime(2026, 10, 31, 16), 'NASDAQ')
    assert market_open(datetime(2026, 10, 30, 16), 'NYSE')
    assert sessions(date(2026, 12, 24), date(2026, 12, 27), 'NYSE') == [date(2026, 12, 24)]
    assert not daily_complete(date(2026, 10, 30), datetime(2026, 10, 30, 16), 'NYSE')
    assert daily_complete(date(2026, 10, 30), datetime(2026, 10, 30, 22), 'NYSE')


def test_prediction_range_widens_with_horizon():
    prices = [100*exp(i*.001 + (i%2)*.01) for i in range(365)]
    a = estimate(prices, 1)
    b = estimate(prices, 365)
    assert b[2]/b[1] > a[2]/a[1]
