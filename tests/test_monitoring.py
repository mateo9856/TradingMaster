"""Private monitoring API and real SQLite worker transactions."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.auth import current_active_user
from app.helpers.time import utc_now_naive
from app.main import app
from app.models.candle import Candle
from app.models.candle_history import CandleHistory
from app.models.exchange import Exchange, Symbol
from app.models.monitoring import MonitoringAlert, MonitoringSettings, MonitoringTarget
from app.models.user import User
from app.monitoring.data import market_data
from app.monitoring.worker import claim, evaluate, run_once
from tests.conftest import TestingSessionLocal

ROOT = '/api/v1/monitoring'


@pytest.fixture
async def actor(client, db_session):
    user = User(id=uuid.uuid4(), email='monitor@example.com', hashed_password='unused', is_active=True)
    exchange = Exchange(name='kraken', method='ohlcv', asset_class='crypto', enabled=True)
    db_session.add_all([user, exchange])
    await db_session.flush()
    db_session.add(Symbol(exchange_id=exchange.id, ticker='BTC/USD', interval='1m', enabled=True))
    await db_session.commit()
    app.dependency_overrides[current_active_user] = lambda: user
    return user


def bar(now, price, model=Candle, interval='1m'):
    args = dict(exchange='kraken', ticker='BTC/USD', interval=interval, timestamp=now,
                open_price=price, high_price=price, low_price=price, close_price=price, volume=1)
    if model is CandleHistory:
        args['trade_date'] = now.date()
    return model(**args)


async def enable(client, **kwargs):
    result = await client.put(ROOT+'/settings', json={'enabled': True, **kwargs})
    assert result.status_code == 200, result.text


async def watch(client):
    result = await client.post(ROOT+'/watchlist', json={'exchange': 'kraken', 'ticker': 'BTC/USD'})
    assert result.status_code == 200, result.text
    return result.json()['data']


@pytest.mark.parametrize('path', ['/settings', '/watchlist', '/holdings', '/alerts'])
async def test_private_reads(anonymous_client, path):
    assert (await anonymous_client.get(ROOT+path)).status_code == 401


async def test_defaults_validation_and_canonical_watch(client, actor):
    settings = (await client.get(ROOT+'/settings')).json()['data']
    assert settings['enabled'] is False
    assert settings['horizon_days'] == 1
    for values in ({'horizon_days': 366}, {'horizon_days': 0}, {'check_minutes': 5}, {'upward_percent': 0}, {'downward_percent': 101}, {'user_id': str(actor.id)}):
        assert (await client.put(ROOT+'/settings', json={'enabled': True, **values})).status_code == 422
    await enable(client, horizon_days=365)
    first = await watch(client)
    assert (await watch(client))['id'] == first['id']
    assert len((await client.get(ROOT+'/watchlist')).json()['data']) == 1


async def test_worker_boundaries_rearm_disable_and_persistent_alerts(client, actor, db_session):
    now = utc_now_naive().replace(second=0, microsecond=0)+timedelta(minutes=1)
    await enable(client)
    await watch(client)
    db_session.add(bar(now-timedelta(minutes=2), 100))
    await db_session.commit()
    assert await run_once(TestingSessionLocal, now) == 1
    for step, price, expected in [(1,110,1),(2,110,1),(3,109,1),(4,110,2),(5,90,3)]:
        when = now+timedelta(hours=step)
        db_session.add(bar(when-timedelta(minutes=2), price))
        await db_session.commit()
        await run_once(TestingSessionLocal, when)
        assert await db_session.scalar(select(func.count()).select_from(MonitoringAlert)) == expected
    alerts = (await client.get(ROOT+'/alerts')).json()['data']
    assert alerts['unread_count'] == 3
    alert_id = alerts['items'][0]['id']
    assert (await client.patch(ROOT+f'/alerts/{alert_id}/read')).status_code == 200
    assert (await client.get(ROOT+'/alerts')).json()['data']['unread_count'] == 2
    await client.put(ROOT+'/settings', json={'enabled': False})
    assert await run_once(TestingSessionLocal, now+timedelta(days=1)) == 0
    assert (await client.get(ROOT+'/alerts')).json()['data']['unread_count'] == 2


async def test_cross_user_isolation(client, actor, db_session):
    own = await watch(client)
    alert = MonitoringAlert(user_id=actor.id, target_id=own['id'], kind='observed', direction='up', episode=1, payload={})
    other = User(id=uuid.uuid4(), email='other@example.com', hashed_password='unused', is_active=True)
    db_session.add_all([other, alert])
    await db_session.commit()
    app.dependency_overrides[current_active_user] = lambda: other
    assert (await client.get(ROOT+'/watchlist')).json()['data'] == []
    assert (await client.get(ROOT+'/alerts')).json()['data']['items'] == []
    assert (await client.get(ROOT+'/alerts', params={'after':'2000-01-01T00:00:00Z'})).json()['data']['items'] == []
    assert (await client.delete(ROOT+'/watchlist/'+own['id'])).status_code == 404
    assert (await client.patch(ROOT+f'/alerts/{alert.id}/read')).status_code == 404


async def test_lease_expiration_stale_claim_settings_and_inactive_user(client, actor, db_session):
    now = utc_now_naive()+timedelta(minutes=1)
    await enable(client)
    await watch(client)
    assert (await client.get(ROOT+'/settings')).json()['data']['enabled'] is True
    async with TestingSessionLocal() as check:
        assert await check.get(User, actor.id) is not None
        assert (await check.get(MonitoringSettings, actor.id)).enabled
    first = await claim(TestingSessionLocal, now)
    assert first
    assert await claim(TestingSessionLocal, now) is None
    second = await claim(TestingSessionLocal, now+timedelta(minutes=6))
    assert second and second[1] != first[1]
    assert not await evaluate(first, TestingSessionLocal, now+timedelta(minutes=6))
    await client.put(ROOT+'/settings', json={'enabled': False})
    assert not await evaluate(second, TestingSessionLocal, now+timedelta(minutes=6))
    await enable(client)
    actor.is_active = False
    await db_session.commit()
    assert await claim(TestingSessionLocal, now+timedelta(minutes=10)) is None


async def test_failed_commit_rolls_back_alert_and_evaluation(client, actor, db_session, monkeypatch):
    from app.monitoring import worker
    now = utc_now_naive()+timedelta(minutes=1)
    await enable(client)
    await watch(client)
    target = await db_session.scalar(select(MonitoringTarget))
    target.reference_price = Decimal(100)
    db_session.add(bar(now-timedelta(minutes=2), 110))
    await db_session.commit()
    original = worker.apply_result
    def fail(*args):
        original(*args)
        raise RuntimeError('interrupted transaction')
    monkeypatch.setattr(worker, 'apply_result', fail)
    claimed = await claim(TestingSessionLocal, now)
    with pytest.raises(RuntimeError):
        await evaluate(claimed, TestingSessionLocal, now)
    assert await db_session.scalar(select(func.count()).select_from(MonitoringAlert)) == 0
    monkeypatch.setattr(worker, 'apply_result', original)
    # A retry after expiry commits exactly one alert.
    later = now+timedelta(minutes=6)
    db_session.add(bar(later-timedelta(minutes=2), 110))
    await db_session.commit()
    await run_once(TestingSessionLocal, later)
    assert await db_session.scalar(select(func.count()).select_from(MonitoringAlert)) == 1


async def test_completed_candles_only_and_archive_overlap(client, actor, db_session, monkeypatch):
    from app.monitoring import data
    now = utc_now_naive().replace(second=30, microsecond=0)
    db_session.add_all([bar(now-timedelta(seconds=30), 999), bar(now-timedelta(minutes=2), 100)])
    day = now.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1)
    db_session.add_all([bar(day, 90, CandleHistory, '1d'), bar(day, 100, Candle, '1d')])
    await db_session.commit()
    captured = []
    def capture(rows, *args):
        captured.extend(rows)
        return {'status': 'insufficient_history'}
    monkeypatch.setattr(data, 'forecast', capture)
    result = await market_data(db_session, 'kraken', 'BTC/USD', now, 1, True)
    assert Decimal(result['price']) == 100
    assert captured == [(day.date(), 100.0)]


async def test_watch_removal_preserves_alerts(client, actor, db_session):
    target = await watch(client)
    db_session.add(MonitoringAlert(user_id=actor.id, target_id=target['id'], kind='observed', direction='up', episode=1, payload={}))
    await db_session.commit()
    assert (await client.delete(ROOT+'/watchlist/'+target['id'])).status_code == 200
    assert (await client.get(ROOT+'/watchlist')).json()['data'] == []
    assert len((await client.get(ROOT+'/alerts')).json()['data']['items']) == 1


async def test_each_purchase_has_own_baseline_and_closed_holdings_stop(client, actor, db_session):
    from app.models.trading import Trade
    now = utc_now_naive()+timedelta(minutes=1)
    await enable(client)
    trades = [Trade(user_id=actor.id, exchange='kraken', ticker='BTC/USD', source_ticker='BTC/USD',
                    quantity=1, buy_price=cost, cost=cost, buy_quote_id=str(uuid.uuid4())) for cost in (100, 150)]
    db_session.add_all(trades)
    db_session.add(bar(now-timedelta(minutes=2), 120))
    await db_session.commit()
    # Holdings exist in the panel before the first worker evaluation.
    assert len((await client.get(ROOT+'/holdings')).json()['data']) == 2
    await run_once(TestingSessionLocal, now)
    alerts = (await client.get(ROOT+'/alerts')).json()['data']['items']
    assert {alert['direction'] for alert in alerts} == {'up', 'down'}
    assert {alert['payload']['trade_id'] for alert in alerts} == {trade.id for trade in trades}
    trades[1].closed_at = now
    await db_session.commit()
    assert len((await client.get(ROOT+'/holdings')).json()['data']) == 1
    await run_once(TestingSessionLocal, now+timedelta(hours=1))
    target = await db_session.scalar(select(MonitoringTarget).where(MonitoringTarget.trade_id == trades[1].id))
    await db_session.refresh(target)
    assert target.active is False


async def test_backfill_resumes_without_duplicate_rows(client, actor, db_session, monkeypatch):
    from app.monitoring import backfill as module
    now = utc_now_naive().replace(hour=0, minute=0, second=0, microsecond=0)-timedelta(days=2)
    async def provider(*args):
        return [[int(now.replace(tzinfo=__import__('datetime').timezone.utc).timestamp()*1000), 100, 110, 90, 105, 1]], []
    monkeypatch.setattr(module, 'AsyncSessionLocal', TestingSessionLocal)
    monkeypatch.setattr(module, 'crypto_rows', provider)
    assert (await module.backfill('kraken', 'BTC/USD'))['inserted'] == 1
    assert (await module.backfill('kraken', 'BTC/USD'))['inserted'] == 0
    assert await db_session.scalar(select(func.count()).select_from(CandleHistory)) == 1


async def test_observed_and_forecast_alerts_have_independent_episodes(client, actor, db_session):
    from app.monitoring.service import apply_result
    await watch(client)
    target = await db_session.scalar(select(MonitoringTarget))
    settings = await db_session.get(MonitoringSettings, actor.id)
    target.reference_price = Decimal(100)
    now = utc_now_naive()
    data = {'status': 'ready', 'price': '110', 'data_at': now.isoformat(),
            'forecast': {'status': 'ready', 'change_percent': '-10', 'reference_price': '110'}}
    apply_result(db_session, target, settings, data, now)
    await db_session.commit()
    apply_result(db_session, target, settings, {'status': 'stale_data'}, now)
    await db_session.commit()
    apply_result(db_session, target, settings, data, now)
    await db_session.commit()
    alerts = (await db_session.scalars(select(MonitoringAlert))).all()
    assert {(alert.kind, alert.direction) for alert in alerts} == {('observed', 'up'), ('forecast', 'down')}
    assert len(alerts) == 2


async def test_stock_weekend_does_not_make_last_session_bar_stale(client, actor, db_session):
    from datetime import datetime

    from app.models.instrument import Instrument
    exchange = Exchange(name='yahoo', method='poll', asset_class='stock', enabled=True)
    db_session.add(exchange)
    await db_session.flush()
    db_session.add(Symbol(exchange_id=exchange.id, ticker='AAPL/USD', interval='1m', enabled=True))
    db_session.add(Instrument(symbol='AAPL', name='Apple', short_name='Apple', slug='apple-aapl', asset_class='stock', venue='NASDAQ'))
    db_session.add(Candle(exchange='yahoo', ticker='AAPL/USD', interval='1m', timestamp=datetime(2026,10,30,19,59),
                          open_price=100, high_price=100, low_price=100, close_price=100, volume=1))
    await db_session.commit()
    assert (await market_data(db_session, 'yahoo', 'AAPL/USD', datetime(2026,10,31,16), 1, False))['status'] == 'market_closed'
    from app.monitoring.data import price_data
    preview = await price_data(db_session, 'yahoo', 'AAPL/USD', datetime(2026,10,31,16), preview=True)
    assert preview['status'] == 'market_closed'
    assert Decimal(preview['snapshot']['price']) == 100
    assert (await market_data(db_session, 'yahoo', 'AAPL/USD', datetime(2026,11,2,14,35), 1, False))['status'] == 'ready'
    assert (await market_data(db_session, 'yahoo', 'AAPL/USD', datetime(2026,11,2,15,30), 1, False))['status'] == 'stale_data'


async def test_only_one_concurrent_worker_claims_account(client, actor):
    import asyncio
    now = utc_now_naive()+timedelta(minutes=1)
    await enable(client)
    results = await asyncio.gather(claim(TestingSessionLocal, now), claim(TestingSessionLocal, now))
    assert sum(result is not None for result in results) == 1


async def test_paused_watch_captures_completed_snapshot_without_alerts(client, actor, db_session):
    now = utc_now_naive().replace(second=30, microsecond=0)
    db_session.add_all([bar(now-timedelta(minutes=2), 100), bar(now-timedelta(seconds=30), 999)])
    await db_session.commit()
    result = await watch(client)
    assert Decimal(result['reference_price']) == 100
    assert Decimal(result['result']['snapshot']['price']) == 100
    assert result['result']['snapshot']['interval'] == '1m'
    assert 'evaluated_at' not in result['result']
    assert 'forecast' not in result['result']
    assert (await client.get(ROOT+'/settings')).json()['data']['enabled'] is False
    assert await db_session.scalar(select(func.count()).select_from(MonitoringAlert)) == 0
    db_session.add(bar(now-timedelta(minutes=1), 200))
    await db_session.commit()
    repeated = await watch(client)
    assert repeated['reference_price'] == result['reference_price']
    assert repeated['result'] == result['result']


async def test_watch_activation_preserves_custom_settings_and_can_be_toggled(client, actor):
    await client.put(ROOT+'/settings', json={'enabled': False, 'upward_percent': '12', 'downward_percent': '8',
                                           'check_minutes': 15, 'horizon_days': 90})
    result = await client.post(ROOT+'/watchlist', json={'exchange':'kraken', 'ticker':'BTC/USD', 'enable_monitoring':True})
    assert result.status_code == 200
    settings = (await client.get(ROOT+'/settings')).json()['data']
    assert settings['enabled'] is True
    assert settings['check_minutes'] == 15
    assert settings['horizon_days'] == 90
    assert Decimal(settings['upward_percent']) == 12
    assert Decimal(settings['downward_percent']) == 8
    disabled = await client.patch(ROOT+'/settings', json={'enabled':False})
    assert disabled.json()['data']['enabled'] is False
    enabled = await client.patch(ROOT+'/settings', json={'enabled':True})
    assert enabled.json()['data']['horizon_days'] == 90
    assert enabled.json()['data']['next_check_at'] is not None
    assert (await client.patch(ROOT+'/settings', json={'enabled':True, 'horizon_days':1})).status_code == 422


async def test_failed_watch_creation_does_not_enable_account(client, actor, monkeypatch):
    from app.routers import monitoring
    await client.get(ROOT+'/settings')
    async def fail(*args, **kwargs):
        raise RuntimeError('snapshot read failed')
    monkeypatch.setattr(monitoring, 'price_data', fail)
    with pytest.raises(RuntimeError):
        await client.post(ROOT+'/watchlist', json={'exchange':'kraken', 'ticker':'BTC/USD', 'enable_monitoring':True})
    assert (await client.get(ROOT+'/settings')).json()['data']['enabled'] is False
    assert (await client.get(ROOT+'/watchlist')).json()['data'] == []


@pytest.mark.parametrize('source', ['forming', 'archived'])
async def test_unusable_prices_never_set_reference(client, actor, db_session, source):
    now = utc_now_naive()
    if source == 'forming':
        db_session.add(bar(now, 999))
    else:
        db_session.add(bar(now-timedelta(days=40), 90, CandleHistory))
    await db_session.commit()
    target = await watch(client)
    assert target['reference_price'] is None
    if source == 'forming':
        assert 'snapshot' not in target['result']
    else:
        assert Decimal(target['result']['snapshot']['price']) == 90
        assert target['result']['snapshot']['status'] == 'stale_data'


async def test_worker_preserves_saved_price_when_source_becomes_unavailable(client, actor, db_session):
    from app.monitoring.service import apply_result
    await watch(client)
    target = await db_session.scalar(select(MonitoringTarget))
    settings = await db_session.get(MonitoringSettings, actor.id)
    now = utc_now_naive()
    ready = {'status':'ready', 'price':'100', 'data_at':now.isoformat(), 'interval':'1m'}
    apply_result(db_session, target, settings, ready, now)
    await db_session.commit()
    for status in ('market_closed', 'stale_data', 'source_error'):
        apply_result(db_session, target, settings, {'status':status}, now)
        await db_session.commit()
        assert target.result['snapshot']['price'] == '100'
        assert target.result['snapshot']['data_at'] == now.isoformat()


async def test_notification_cursor_drains_equal_timestamps_without_duplicates(client, actor, db_session):
    from datetime import timezone
    now = utc_now_naive()
    ids = [str(uuid.UUID(int=i)) for i in range(1, 121)]
    db_session.add_all([MonitoringAlert(id=key, user_id=actor.id, target_id=str(uuid.uuid4()),
        kind='forecast', direction='up', episode=1, payload={}, created_at=now) for key in ids])
    await db_session.commit()
    initial = (await client.get(ROOT+'/alerts')).json()['data']
    assert initial['items'][0]['id'] == ids[-1]
    assert initial['checked_at']
    after = now.replace(tzinfo=timezone.utc).isoformat()
    first = (await client.get(ROOT+'/alerts', params={'after':after, 'limit':100})).json()['data']
    assert [row['id'] for row in first['items']] == ids[:100]
    second = (await client.get(ROOT+'/alerts', params={'after':after, 'after_id':ids[99], 'limit':100})).json()['data']
    assert [row['id'] for row in second['items']] == ids[100:]
    assert second['unread_count'] == 120
    empty = (await client.get(ROOT+'/alerts', params={'after':after, 'after_id':ids[-1]})).json()['data']
    assert empty['items'] == []
    assert (await client.get(ROOT+'/alerts', params={'after_id':ids[0]})).status_code == 422
