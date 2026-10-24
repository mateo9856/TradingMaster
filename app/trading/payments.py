"""Deterministic simulated authorization; never contacts a payment provider."""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.helpers.time import utc_now_naive
from app.models.trading import PaymentAccount


def transaction_limit(kind: str) -> Decimal:
    return getattr(config, f"SIMULATED_{kind.upper()}_TRANSACTION_LIMIT")


def authorize(kind: str, balance: Decimal, amount: Decimal) -> Decimal:
    if amount > transaction_limit(kind):
        raise HTTPException(409, "Payment transaction limit exceeded")
    if kind == "credit":
        if balance + amount > config.SIMULATED_CREDIT_LIMIT:
            raise HTTPException(409, "Insufficient available credit")
        return balance + amount
    if balance < amount:
        raise HTTPException(409, "Insufficient simulated payment funds")
    return balance - amount


async def seed_accounts(db: AsyncSession, user_id) -> None:
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    for kind, balance in (("debit", config.SIMULATED_DEBIT_BALANCE),
                          ("credit", config.SIMULATED_CREDIT_INITIAL_DEBT),
                          ("paypal", config.SIMULATED_PAYPAL_BALANCE)):
        await db.execute(insert(PaymentAccount).values(user_id=user_id, kind=kind, balance=balance,
                                                       created_at=utc_now_naive())
                         .on_conflict_do_nothing(index_elements=[PaymentAccount.user_id, PaymentAccount.kind]))


async def charge(db: AsyncSession, user_id, method: str, card_type: str | None,
                 amount: Decimal) -> PaymentAccount:
    # Caller holds the user's wallet lock for the whole authorization/commit.
    await seed_accounts(db, user_id)
    account = await db.get(PaymentAccount, (user_id, card_type if method == "card" else method),
                           populate_existing=True)
    account.balance = authorize(account.kind, account.balance, amount)
    return account


async def accounts_data(db: AsyncSession, user_id) -> dict:
    from .service import number

    accounts = (await db.scalars(select(PaymentAccount).where(PaymentAccount.user_id == user_id))).all()
    result = {}
    for account in accounts:
        credit = account.kind == "credit"
        available = max(Decimal(0), config.SIMULATED_CREDIT_LIMIT - account.balance) if credit else account.balance
        result[account.kind] = {
            "available": number(available), "balance": number(account.balance) if not credit else None,
            "debt": number(account.balance) if credit else None,
            "credit_limit": number(config.SIMULATED_CREDIT_LIMIT) if credit else None,
            "transaction_limit": number(transaction_limit(account.kind)),
        }
    return {"simulated": True, "currency": "USD", "accounts": result}
