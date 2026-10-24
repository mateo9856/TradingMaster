"""Real database payment, wallet and execution transactions through the API."""

import asyncio
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import event, func, select

from app import config
from app.auth import current_active_user
from app.models.exchange import Exchange, Symbol
from app.models.trading import CreditEntry, Payment, PaymentAccount, Trade, TradingQuote, Wallet
from app.models.user import User
from tests.test_trading import PREFIX, buy_quote, enable_trading, key, price, trader

METHODS = [('credits', None), ('card', 'debit'), ('card', 'credit'), ('paypal', None)]


def selection(method, card_type):
    return {'payment_method': method, **({'card_type': card_type} if card_type else {})}


@pytest.mark.parametrize('method,card_type', METHODS)
@pytest.mark.parametrize('stock', [False, True])
async def test_purchases_and_sales_record_funding(trader, db_session, method, card_type, stock):
    if stock:
        exchange = Exchange(name='yahoo', method='poll', asset_class='stock')
        db_session.add(exchange)
        await db_session.flush()
        db_session.add(Symbol(exchange_id=exchange.id, ticker='AAPL/USD', interval='1m'))
        await db_session.commit()
        quote_response = await trader.post(PREFIX + '/quotes', json={
            'side': 'buy', 'exchange': 'yahoo', 'ticker': 'AAPL/USD', 'budget': '100'})
        assert quote_response.status_code == 200, quote_response.text
        quote = quote_response.json()['data']
    else:
        quote = await buy_quote(trader)
    headers = key()
    body = {'quote_id': quote['id'], **selection(method, card_type)}
    first = await trader.post(PREFIX + '/trades', json=body, headers=headers)
    assert first.status_code == 200, first.text
    retry = await trader.post(PREFIX + '/trades', json=body, headers=headers)
    assert retry.json() == first.json()
    expected = '900.00000000' if method == 'credits' else '1000.00000000'
    assert first.json()['data']['wallet']['balance'] == expected
    record = await db_session.scalar(select(Payment))
    assert (record.method, record.card_type, record.amount) == (method, card_type, Decimal('100'))
    assert record.wallet_delta == (-100 if method == 'credits' else 0)
    accounts = (await trader.get(PREFIX + '/payment-accounts')).json()['data']['accounts']
    if method != 'credits':
        kind = card_type or method
        assert accounts[kind]['available'] == '9900.00000000'
        if kind == 'credit':
            assert accounts[kind]['debt'] == '100.00000000'
    trade_id = first.json()['data']['trade']['id']
    sale_quote = (await trader.post(PREFIX + '/quotes', json={'side': 'sell', 'trade_id': trade_id})).json()['data']
    sold = await trader.post(PREFIX + f'/trades/{trade_id}/sell', json={'quote_id': sale_quote['id']}, headers=key())
    assert sold.status_code == 200, sold.text
    assert sold.json()['data']['wallet']['balance'] == ('999.00000000' if method == 'credits' else '1099.00000000')
    assert sold.json()['data']['trade']['realized_pnl'] == '-1.00000000'
    assert (await trader.get(PREFIX + '/payment-accounts')).json()['data']['accounts'] == accounts


@pytest.mark.parametrize('method,card_type', METHODS)
async def test_low_wallet_only_blocks_credit_payments(trader, db_session, method, card_type):
    wallet = await db_session.scalar(select(Wallet))
    wallet.balance = Decimal('10')
    await db_session.commit()
    quote = await buy_quote(trader)
    response = await trader.post(PREFIX + '/trades', json={'quote_id': quote['id'], **selection(method, card_type)}, headers=key())
    assert response.status_code == (409 if method == 'credits' else 200)
    assert (await trader.get(PREFIX + '/wallet')).json()['data']['balance'] == '10.00000000'


@pytest.mark.parametrize('method,card_type', METHODS[1:])
async def test_funding_is_persisted_and_idempotent(trader, db_session, monkeypatch, method, card_type):
    headers = key()
    body = {'amount': '100', **selection(method, card_type)}
    first = await trader.post(PREFIX + '/wallet/top-ups', json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()['data']['balance'] == '1100.00000000'
    retry = await trader.post(PREFIX + '/wallet/top-ups', json={**body, 'amount': '100.000'}, headers=headers)
    assert retry.json() == first.json()
    assert await db_session.scalar(select(func.count()).select_from(Payment)) == 1
    record = await db_session.scalar(select(Payment))
    assert record.wallet_delta == 100 and record.trade_id is None
    # Restart/configuration changes never replenish spent funds or erase debt.
    monkeypatch.setattr(config, 'SIMULATED_DEBIT_BALANCE', Decimal('99999'))
    monkeypatch.setattr(config, 'SIMULATED_PAYPAL_BALANCE', Decimal('99999'))
    monkeypatch.setattr(config, 'SIMULATED_CREDIT_INITIAL_DEBT', Decimal('500'))
    await trader.post(PREFIX + '/wallet/initialize')
    accounts = (await trader.get(PREFIX + '/payment-accounts')).json()['data']['accounts']
    assert accounts[card_type or method]['available'] == '9900.00000000'
    # Limits apply to subsequent transactions without reseeding accounts.
    monkeypatch.setattr(config, f'SIMULATED_{(card_type or method).upper()}_TRANSACTION_LIMIT', Decimal('99'))
    decline = await trader.post(PREFIX + '/wallet/top-ups', json=body, headers=key())
    assert decline.status_code == 409
    # Successful retries remain successful even after the configuration changes.
    assert (await trader.post(PREFIX + '/wallet/top-ups', json=body, headers=headers)).json() == first.json()


@pytest.mark.parametrize('kind', ['debit', 'credit', 'paypal'])
@pytest.mark.parametrize('funding', [False, True])
async def test_declines_leave_no_partial_movement(trader, db_session, kind, funding):
    account = await db_session.scalar(select(PaymentAccount).where(PaymentAccount.kind == kind))
    account.balance = Decimal('9990') if kind == 'credit' else Decimal('10')
    await db_session.commit()
    payment = selection('paypal' if kind == 'paypal' else 'card', None if kind == 'paypal' else kind)
    quote = await buy_quote(trader)
    path = '/wallet/top-ups' if funding else '/trades'
    body = {'amount': '100'} if funding else {'quote_id': quote['id']}
    response = await trader.post(PREFIX + path, json={**body, **payment}, headers=key())
    assert response.status_code == 409, response.text
    await db_session.refresh(account)
    assert account.balance == (Decimal('9990') if kind == 'credit' else Decimal('10'))
    assert (await trader.get(PREFIX + '/wallet')).json()['data']['balance'] == '1000.00000000'
    assert await db_session.scalar(select(func.count()).select_from(Trade)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Payment)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CreditEntry)) == 1
    assert (await db_session.get(TradingQuote, quote['id'])).consumed_at is None


@pytest.mark.parametrize('method,card_type', METHODS)
async def test_payment_selection_is_part_of_idempotency(trader, method, card_type):
    quote = await buy_quote(trader)
    headers = key()
    first = await trader.post(PREFIX + '/trades', json={'quote_id': quote['id'], **selection(method, card_type)}, headers=headers)
    assert first.status_code == 200
    changed = selection('card', 'debit' if card_type != 'debit' else 'credit')
    conflict = await trader.post(PREFIX + '/trades', json={'quote_id': quote['id'], **changed}, headers=headers)
    assert conflict.status_code == 409 and 'Idempotency' in conflict.text


async def test_concurrent_retries_charge_once(trader, db_session):
    quote = await buy_quote(trader)
    headers = key()
    body = {'quote_id': quote['id'], 'payment_method': 'paypal'}
    results = await asyncio.gather(*[trader.post(PREFIX + '/trades', json=body, headers=headers) for _ in range(2)])
    assert all(result.status_code == 200 for result in results)
    assert results[0].json() == results[1].json()
    assert await db_session.scalar(select(func.count()).select_from(Payment)) == 1
    assert (await trader.get(PREFIX + '/payment-accounts')).json()['data']['accounts']['paypal']['available'] == '9900.00000000'


async def test_funding_idempotency_conflicts_on_method_or_amount_change(trader):
    headers = key()
    body = {'amount': '100', 'payment_method': 'paypal'}
    assert (await trader.post(PREFIX + '/wallet/top-ups', json=body, headers=headers)).status_code == 200
    for changed in ({'amount': '101', 'payment_method': 'paypal'},
                    {'amount': '100', 'payment_method': 'card', 'card_type': 'debit'}):
        response = await trader.post(PREFIX + '/wallet/top-ups', json=changed, headers=headers)
        assert response.status_code == 409 and 'Idempotency' in response.text


@pytest.mark.parametrize('kind', ['debit', 'credit', 'paypal'])
async def test_concurrent_external_spending_cannot_overspend(trader, db_session, kind):
    account = await db_session.scalar(select(PaymentAccount).where(PaymentAccount.kind == kind))
    account.balance = Decimal('100') if kind != 'credit' else Decimal('9900')
    await db_session.commit()
    payment = selection('paypal' if kind == 'paypal' else 'card', None if kind == 'paypal' else kind)
    quote = await buy_quote(trader)
    # A purchase races a deposit against the SAME external funds.
    results = await asyncio.gather(
        trader.post(PREFIX + '/trades', json={'quote_id': quote['id'], **payment}, headers=key()),
        trader.post(PREFIX + '/wallet/top-ups', json={'amount': '100', **payment}, headers=key()),
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    assert await db_session.scalar(select(func.count()).select_from(Payment)) == 1
    await db_session.refresh(account)
    assert account.balance == (Decimal('10000') if kind == 'credit' else 0)


@pytest.mark.parametrize('funding', [False, True])
async def test_payment_persistence_failure_rolls_back_all_changes(trader, db_session, funding):
    quote = await buy_quote(trader)
    def fail(*args):
        raise RuntimeError('payment insert failed')
    event.listen(Payment, 'before_insert', fail)
    try:
        with pytest.raises(RuntimeError, match='payment insert failed'):
            await trader.post(PREFIX + ('/wallet/top-ups' if funding else '/trades'), json={
                **({'amount': '100'} if funding else {'quote_id': quote['id']}),
                'payment_method': 'card', 'card_type': 'debit'}, headers=key())
    finally:
        event.remove(Payment, 'before_insert', fail)
    assert (await trader.get(PREFIX + '/wallet')).json()['data']['balance'] == '1000.00000000'
    accounts = (await trader.get(PREFIX + '/payment-accounts')).json()['data']['accounts']
    assert accounts['debit']['available'] == '10000.00000000'
    assert await db_session.scalar(select(func.count()).select_from(Trade)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Payment)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CreditEntry)) == 1
    assert (await db_session.get(TradingQuote, quote['id'])).consumed_at is None


async def test_accounts_are_private_and_isolated(trader, db_session):
    from app.main import app
    await trader.post(PREFIX + '/wallet/top-ups', json={'amount': '100', 'payment_method': 'paypal'}, headers=key())
    other = User(id=uuid.uuid4(), email='other-payment@example.com', hashed_password='unused', is_active=True)
    db_session.add(other)
    await db_session.commit()
    app.dependency_overrides[current_active_user] = lambda: other
    accounts = await trader.get(PREFIX + '/payment-accounts')
    assert accounts.status_code == 200
    assert accounts.json()['data']['accounts']['paypal']['available'] == '10000.00000000'
    assert (await trader.get(PREFIX + '/wallet')).json()['data']['balance'] == '1000.00000000'
    bad = await trader.post(PREFIX + '/wallet/top-ups', json={
        'amount': '1', 'payment_method': 'paypal', 'user_id': str(uuid.uuid4())}, headers=key())
    assert bad.status_code == 422
    app.dependency_overrides.pop(current_active_user)
    assert (await trader.get(PREFIX + '/payment-accounts')).status_code == 401
    assert (await trader.post(PREFIX + '/wallet/top-ups', json={'amount': '1', 'payment_method': 'paypal'}, headers=key())).status_code == 401


@pytest.mark.parametrize('body', [
    {'payment_method': 'card'}, {'payment_method': 'credits', 'card_type': 'debit'},
    {'payment_method': 'paypal', 'card_type': 'credit'}, {'payment_method': 'bank'},
])
async def test_invalid_selection_is_rejected(trader, body):
    quote = await buy_quote(trader)
    assert (await trader.post(PREFIX + '/trades', json={'quote_id': quote['id'], **body}, headers=key())).status_code == 422


async def test_production_feature_switch_and_demo_restriction(trader, monkeypatch):
    monkeypatch.setattr(config, 'APP_ENV', 'production')
    monkeypatch.setattr(config, 'DEV_TRADING_ENABLED', False)
    monkeypatch.setattr(config, 'SIMULATED_TRADING_ENABLED', True)
    assert (await trader.get(PREFIX + '/capabilities')).json()['data']['payment_methods']['card'] == 'enabled'
    quote = await buy_quote(trader)
    assert (await trader.post(PREFIX + '/trades', json={'quote_id': quote['id'], 'payment_method': 'paypal'}, headers=key())).status_code == 200
    assert (await trader.post(PREFIX + '/wallet/top-ups', json={'amount': '100', 'payment_method': 'paypal'}, headers=key())).status_code == 200
    assert (await trader.post(PREFIX + '/wallet/demo-top-ups', json={'amount': '100'}, headers=key())).status_code == 404
    monkeypatch.setattr(config, 'SIMULATED_TRADING_ENABLED', False)
    assert (await trader.get(PREFIX + '/payment-accounts')).status_code == 404
