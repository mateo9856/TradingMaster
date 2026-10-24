"""Run the payment revision against existing trading records without PostgreSQL."""

import importlib.util
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.helpers.time import utc_now_naive
from app.models import Base
from app.models.trading import CreditEntry, Payment, PaymentAccount, Trade, TradingQuote, Wallet
from app.models.user import User


def test_payment_revision_preserves_history_and_matches_models(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    existing = [table for table in Base.metadata.sorted_tables
                if table.name not in ('trading_payments', 'trading_payment_accounts')]
    Base.metadata.create_all(engine, tables=existing)
    user_id = uuid.uuid4()
    now = utc_now_naive()
    with Session(engine) as db:
        db.add(User(id=user_id, email='migration@example.com', hashed_password='unused', is_active=True))
        db.flush()
        db.add(Wallet(user_id=user_id, balance=Decimal('42.12345678')))
        quote = TradingQuote(id=str(uuid.uuid4()), user_id=user_id, side='buy', exchange='kraken', ticker='BTC/USD',
                             source_ticker='BTC/USD', bid=99, ask=100, fx_rate=1, quantity=1, amount=100,
                             received_at=now, expires_at=now + timedelta(seconds=15), delayed=False)
        db.add(quote)
        db.flush()
        db.add(Trade(user_id=user_id, exchange='kraken', ticker='BTC/USD', source_ticker='BTC/USD',
                     quantity=1, buy_price=100, cost=100, buy_quote_id=quote.id))
        db.add(CreditEntry(user_id=user_id, action='buy', amount=-100, balance_after=Decimal('42.12345678'),
                           request_key='old-key', fingerprint='old-fingerprint', result={'legacy': True}))
        db.commit()
    path = Path(__file__).resolve().parents[2] / 'migrations/versions/2026_10_24_1200-0007_simulated_payments.py'
    spec = importlib.util.spec_from_file_location('payment_revision', path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            revision.upgrade()
        assert compare_metadata(context, Base.metadata) == []
    with Session(engine) as db:
        assert db.get(Wallet, user_id).balance == Decimal('42.12345678')
        assert db.scalar(select(Trade)).cost == Decimal('100')
        assert db.scalar(select(CreditEntry)).result == {'legacy': True}
        assert db.scalar(select(Payment)) is None
        assert db.scalar(select(PaymentAccount)) is None
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            revision.downgrade()
        assert 'trading_payments' not in inspect(conn).get_table_names()
        assert conn.scalar(select(Wallet.balance)) == Decimal('42.12345678')
        assert conn.scalar(select(Trade.cost)) == Decimal('100')
        assert conn.scalar(select(CreditEntry.request_key)) == 'old-key'
    engine.dispose()
