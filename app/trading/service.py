"""Paper execution and credit accounting, serialized by the wallet row in SQL."""

import hashlib
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.helpers.markets import unified_ticker
from app.helpers.time import utc_now_naive
from app.models.trading import CreditEntry, Payment, Trade, TradingQuote, Wallet
from app.schemas.trading import QuoteRequest
from .quotes import PriceQuote, QuoteUnavailable, quote_service, resolve_source
from .payments import charge, seed_accounts

logger = logging.getLogger(__name__)
QUANTUM = Decimal("0.00000001")
MAX_AMOUNT = Decimal("1e20")


def money(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) >= MAX_AMOUNT:
        raise HTTPException(422, "Amount is outside the supported range")
    return value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def number(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.8f}"


def iso(value) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


def wallet_data(wallet: Wallet) -> dict:
    return {"balance": number(wallet.balance), "currency": "credits", "usd_per_credit": "1.00000000"}


def quote_data(quote: TradingQuote) -> dict:
    spread = quote.ask - quote.bid
    return {
        "id": quote.id, "side": quote.side, "exchange": quote.exchange, "ticker": quote.ticker,
        "source_ticker": quote.source_ticker, "quantity": number(quote.quantity),
        "amount": number(quote.amount), "bid": number(quote.bid), "ask": number(quote.ask),
        "spread": number(spread), "spread_percent": number(spread / ((quote.ask + quote.bid) / 2) * 100),
        "fx_rate": number(quote.fx_rate), "source_at": iso(quote.source_at),
        "received_at": iso(quote.received_at), "expires_at": iso(quote.expires_at),
        "delayed": quote.delayed, "trade_id": quote.trade_id,
    }


def trade_data(trade: Trade) -> dict:
    return {
        "id": trade.id, "exchange": trade.exchange, "ticker": trade.ticker,
        "source_ticker": trade.source_ticker, "quantity": number(trade.quantity),
        "buy_price": number(trade.buy_price), "cost": number(trade.cost),
        "status": "closed" if trade.closed_at else "open", "opened_at": iso(trade.opened_at),
        "closed_at": iso(trade.closed_at), "sell_price": number(trade.sell_price),
        "proceeds": number(trade.proceeds),
        "realized_pnl": number(trade.proceeds - trade.cost) if trade.proceeds is not None else None,
    }


async def initialize_wallet(db: AsyncSession, user_id) -> dict:
    # INSERT .. ON CONFLICT is atomic across API workers and repeat requests.
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    created = await db.scalar(
        insert(Wallet).values(user_id=user_id, balance=config.TRADING_INITIAL_CREDITS,
                              version=0, created_at=utc_now_naive())
        .on_conflict_do_nothing(index_elements=[Wallet.user_id]).returning(Wallet.user_id)
    )
    wallet = await db.get(Wallet, user_id)
    result = wallet_data(wallet)
    if created is not None:
        db.add(CreditEntry(user_id=user_id, action="initial", amount=wallet.balance,
                           balance_after=wallet.balance, request_key="initial", fingerprint="initial",
                           result=result))
    await seed_accounts(db, user_id)
    await db.commit()
    return result


async def find_trade(db: AsyncSession, user_id, trade_id: str) -> Trade:
    trade = await db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id))
    if trade is None:
        raise HTTPException(404, "Trade not found")
    return trade


async def preview(db: AsyncSession, user_id, request: QuoteRequest) -> dict:
    if await db.get(Wallet, user_id) is None:
        raise HTTPException(409, "Initialize the trading wallet first")
    trade = None
    if request.side == "sell":
        trade = await find_trade(db, user_id, str(request.trade_id))
        if trade.closed_at:
            raise HTTPException(409, "Trade is already closed")
        exchange, ticker, exact = trade.exchange, trade.ticker, trade.source_ticker
    else:
        exchange, exact = request.exchange, None
        try:
            ticker = unified_ticker(request.ticker)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    try:
        source = await resolve_source(db, exchange, ticker, exact)
        price, fx = await quote_service.get(db, source)
    except QuoteUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    quantity = trade.quantity if trade is not None else request.budget / price.ask
    if quantity >= MAX_AMOUNT:
        raise HTTPException(422, "Quantity is outside the supported range")
    quantity = quantity.quantize(QUANTUM, rounding=ROUND_DOWN)
    amount = money(quantity * (price.bid if trade is not None else price.ask))
    if quantity <= 0 or amount <= 0 or quantity >= MAX_AMOUNT or amount >= MAX_AMOUNT:
        raise HTTPException(422, "Purchase or sale is outside the supported amount range")
    now = utc_now_naive()
    max_age = config.TRADING_STOCK_MAX_AGE_SECONDS if price.delayed else config.TRADING_CRYPTO_MAX_AGE_SECONDS
    expires = min(now + timedelta(seconds=15), price.received_at + timedelta(seconds=15),
                  (price.source_at or price.received_at) + timedelta(seconds=max_age))
    if price.session_end:
        expires = min(expires, price.session_end)
    quote = TradingQuote(
        user_id=user_id, side=request.side, exchange=exchange, ticker=ticker, source_ticker=source.source_ticker,
        trade_id=trade.id if trade else None, bid=price.bid, ask=price.ask, fx_rate=fx,
        quantity=quantity, amount=amount, source_at=price.source_at, received_at=price.received_at,
        expires_at=expires, delayed=price.delayed,
    )
    db.add(quote)
    await db.flush()
    result = quote_data(quote)
    await db.commit()
    return result


async def lock_wallet(db: AsyncSession, user_id) -> Wallet:
    # An UPDATE acquires the wallet write lock on both PostgreSQL and SQLite.
    # Read balance and idempotency records only AFTER acquiring it. Request
    # sessions roll back automatically if validation or persistence fails.
    changed = await db.execute(update(Wallet).where(Wallet.user_id == user_id)
                               .values(version=Wallet.version + 1))
    if not changed.rowcount:
        raise HTTPException(409, "Initialize the trading wallet first")
    return await db.get(Wallet, user_id, populate_existing=True)


async def replay(db: AsyncSession, user_id, key: str, fingerprint: str) -> dict | None:
    entry = await db.scalar(select(CreditEntry).where(CreditEntry.user_id == user_id,
                                                    CreditEntry.request_key == key))
    if entry is None:
        return None
    if entry.fingerprint != fingerprint:
        raise HTTPException(409, "Idempotency key was already used for a different request")
    await db.commit()
    return entry.result


async def execute(db: AsyncSession, user_id, key: str, quote_id: str,
                  trade_id: str | None = None, payment_method: str = "credits",
                  card_type: str | None = None) -> dict:
    action = "sell" if trade_id is not None else "buy"
    identity = f"{action}:{quote_id}:{trade_id}"
    # Preserve fingerprints for old credit purchases and sales.
    if payment_method != "credits":
        identity += f":{payment_method}:{card_type}"
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    wallet = await lock_wallet(db, user_id)
    previous = await replay(db, user_id, key, fingerprint)
    if previous is not None:
        return previous
    quote = await db.scalar(select(TradingQuote).where(TradingQuote.id == quote_id,
                                                    TradingQuote.user_id == user_id))
    if quote is None:
        raise HTTPException(404, "Quote not found")
    if quote.side != action or quote.trade_id != trade_id:
        raise HTTPException(409, "Quote does not match this action")
    if quote.consumed_at or quote.expires_at <= utc_now_naive():
        raise HTTPException(409, "Quote expired or was already used; request a new preview")
    try:
        await resolve_source(db, quote.exchange, quote.ticker, quote.source_ticker)
    except QuoteUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    account = None
    if action == "buy":
        if payment_method == "credits" and wallet.balance < quote.amount:
            raise HTTPException(409, "Insufficient credits")
        if payment_method != "credits":
            account = await charge(db, user_id, payment_method, card_type, quote.amount)
        trade = Trade(user_id=user_id, exchange=quote.exchange, ticker=quote.ticker,
                      source_ticker=quote.source_ticker, quantity=quote.quantity,
                      buy_price=quote.ask, cost=quote.amount, buy_quote_id=quote.id)
        db.add(trade)
        delta = -quote.amount if payment_method == "credits" else Decimal(0)
    else:
        trade = await find_trade(db, user_id, trade_id)
        if trade.closed_at or trade.quantity != quote.quantity:
            raise HTTPException(409, "Trade is already closed or has changed")
        trade.sell_quote_id, trade.sell_price = quote.id, quote.bid
        trade.proceeds, trade.closed_at = quote.amount, utc_now_naive()
        delta = quote.amount
    if wallet.balance + delta >= MAX_AMOUNT:
        raise HTTPException(409, "Wallet balance limit exceeded")
    wallet.balance = money(wallet.balance + delta)
    quote.consumed_at = utc_now_naive()
    await db.flush()
    result = {"wallet": wallet_data(wallet), "trade": trade_data(trade)}
    entry = CreditEntry(user_id=user_id, action=action, amount=delta, balance_after=wallet.balance,
                        request_key=key, fingerprint=fingerprint, result=result)
    db.add(entry)
    if action == "buy":
        await db.flush()
        db.add(Payment(entry_id=entry.id, trade_id=trade.id, method=payment_method, card_type=card_type,
                       amount=quote.amount, wallet_delta=delta,
                       account_balance_after=account.balance if account else None))
    await db.commit()
    logger.info("Simulated %s user_id=%s trade_id=%s quote_id=%s", action, user_id, trade.id, quote.id)
    return result


async def top_up(db: AsyncSession, user_id, key: str, amount: Decimal) -> dict:
    amount = money(amount)
    fingerprint = hashlib.sha256(f"top_up:{number(amount)}".encode()).hexdigest()
    wallet = await lock_wallet(db, user_id)
    previous = await replay(db, user_id, key, fingerprint)
    if previous is not None:
        return previous
    if wallet.balance + amount >= MAX_AMOUNT:
        raise HTTPException(409, "Wallet balance limit exceeded")
    wallet.balance = money(wallet.balance + amount)
    result = wallet_data(wallet)
    entry = CreditEntry(user_id=user_id, action="demo_top_up", amount=amount, balance_after=wallet.balance,
                        request_key=key, fingerprint=fingerprint, result=result)
    db.add(entry)
    await db.flush()
    db.add(Payment(entry_id=entry.id, method="credits", amount=amount, wallet_delta=amount))
    await db.commit()
    logger.info("Demo credits added user_id=%s", user_id)
    return result


async def fund_wallet(db: AsyncSession, user_id, key: str, amount: Decimal,
                      payment_method: str, card_type: str | None) -> dict:
    amount = money(amount)
    fingerprint = hashlib.sha256(f"fund:{number(amount)}:{payment_method}:{card_type}".encode()).hexdigest()
    wallet = await lock_wallet(db, user_id)
    previous = await replay(db, user_id, key, fingerprint)
    if previous is not None:
        return previous
    if wallet.balance + amount >= MAX_AMOUNT:
        raise HTTPException(409, "Wallet balance limit exceeded")
    account = await charge(db, user_id, payment_method, card_type, amount)
    wallet.balance = money(wallet.balance + amount)
    result = wallet_data(wallet)
    entry = CreditEntry(user_id=user_id, action="top_up", amount=amount, balance_after=wallet.balance,
                        request_key=key, fingerprint=fingerprint, result=result)
    db.add(entry)
    await db.flush()
    db.add(Payment(entry_id=entry.id, method=payment_method, card_type=card_type, amount=amount,
                   wallet_delta=amount, account_balance_after=account.balance))
    await db.commit()
    return result


def valuation(price: PriceQuote, trade: Trade) -> dict:
    value = money(trade.quantity * price.bid)
    spread = price.ask - price.bid
    pnl = value - trade.cost
    return {
        "sell_value": number(value), "unrealized_pnl": number(pnl),
        "pnl_percent": number(pnl / trade.cost * 100),
        "bid": number(price.bid), "ask": number(price.ask), "spread": number(spread),
        "spread_percent": number(spread / ((price.ask + price.bid) / 2) * 100),
        "source_at": iso(price.source_at), "received_at": iso(price.received_at), "delayed": price.delayed,
    }
