import asyncio
import logging
from typing import List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.fiat.convert import RateUnavailableError, convert_candles, convert_live, resolve_currency
from app.fiat.rates import fiat_rates
from app.config import (
    MARKET_MAX_PAGE_SIZE,
    WS_HEARTBEAT_SECONDS,
    WS_MAX_CONNECTIONS,
    WS_MAX_CONNECTIONS_PER_IP,
)
from app.helpers.currencies import validate_currency
from app.helpers.intervals import SUPPORTED_INTERVALS, validate_interval
from app.helpers.markets import source_ticker_candidates, topic_ticker, unified_ticker
from app.kafka.stream_hub import stream_hub
from app.metrics import websocket_active_connections, websocket_connections_rejected_total
from app.middleware.rate_limit import check_websocket_connect, client_key
from app.models.candle import Candle
from app.models.database import AsyncSessionLocal, get_db
from app.models.exchange import Exchange, Symbol
from app.models.user import User
from app.schemas import ApiResponse, CandleCreate, CandleResponse, MarketResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/market",
    tags=["market"],
    responses={
        404: {"description": "Not found"},
        200: {"description": "Successful response"},
        500: {"description": "Internal server error"},
    },
)

# Close code 1013 ("try again later") tells a browser this is a temporary
# capacity problem, distinct from 1008 ("no such market"), which the UI treats
# as permanent and does not retry (frontend/src/hooks/useLiveCandles.ts).
WS_TRY_AGAIN_LATER = 1013

# Live connections in this process, for the caps below.
_open_connections: int = 0
_connections_per_ip: dict[str, int] = {}


def resolve_ticker(ticker: str) -> str:
    """
    Any spelling of a market (BTC/USDT, BTC%2FUSD, btc-usdc, BTCUSDT) → the
    unified USD ticker the feed stores it under ("BTC/USD"). 422 if the quote
    currency isn't USD-equivalent.
    """
    try:
        return unified_ticker(unquote(ticker))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


def resolve_interval(interval: str) -> str:
    """422 for an unsupported interval, rather than an empty result and a 404."""
    try:
        return validate_interval(interval)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


# ── REST: market list ────────────────────────────────────────────────────────

@router.get("/markets", response_model=ApiResponse[List[MarketResponse]])
async def list_markets(db: AsyncSession = Depends(get_db)):
    """
    Markets currently collected, as the unified feed publishes them — one entry
    per unified ticker, with the exchanges feeding it and the intervals
    available. Public; this is what a UI's market picker is built from.
    """
    result = await db.execute(
        select(Exchange.name, Exchange.asset_class, Symbol.ticker, Symbol.interval)
        .join(Symbol, Symbol.exchange_id == Exchange.id)
        .where(Exchange.enabled == True, Symbol.enabled == True)  # noqa: E712
    )

    markets: dict[str, dict[str, set]] = {}
    asset_classes: dict[str, str] = {}
    for exchange_name, asset_class, source_ticker, interval in result.all():
        if interval not in SUPPORTED_INTERVALS:
            continue
        try:
            unified = unified_ticker(source_ticker)
        except ValueError:
            continue   # legacy row the unified feed can't publish
        entry = markets.setdefault(unified, {"exchanges": set(), "intervals": set()})
        entry["exchanges"].add(exchange_name)
        entry["intervals"].add(interval)
        asset_classes.setdefault(unified, asset_class or "crypto")

    data = [
        MarketResponse(
            ticker=ticker,
            asset_class=asset_classes[ticker],
            exchanges=sorted(entry["exchanges"]),
            intervals=sorted(entry["intervals"], key=SUPPORTED_INTERVALS.index),
        )
        for ticker, entry in sorted(markets.items())
    ]
    return ApiResponse(status="success", message=f"Found {len(data)} market(s)", data=data)


# ── REST: GET candles ─────────────────────────────────────────────────────────

@router.get(
    "/candles/{ticker:path}",
    response_model=ApiResponse[List[CandleResponse]],
)
async def get_candles(
    ticker: str,
    exchange: Optional[str] = None,   # optional filter by exchange
    interval: str = "1m",
    limit: int = Query(100, ge=1, le=MARKET_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    currency: Optional[str] = Query(
        None, examples=["PLN"], description="Show prices in this currency (ECB rate of each candle's date); default USD",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Get historical candles for a ticker, in the unified format (USD prices,
    or `currency` when given). BTC/USDT, BTC/USD and BTCUSDT all resolve to
    the unified BTC/USD market. Optionally filter by exchange and interval.
    """
    ticker_upper = resolve_ticker(ticker)
    interval = resolve_interval(interval)
    currency = resolve_currency(currency)

    query = (
        select(Candle)
        .where(Candle.ticker == ticker_upper)
        .where(Candle.interval == interval)
        .order_by(Candle.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )

    if exchange:
        query = query.where(Candle.exchange == exchange.lower())

    result = await db.execute(query)
    candles = result.scalars().all()

    if not candles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candles found for {ticker_upper} at interval {interval}.",
        )

    return ApiResponse(
        status="success",
        message=f"Found {len(candles)} candle(s) for {ticker_upper}",
        data=await convert_candles(db, [CandleResponse.model_validate(c) for c in candles], currency),
    )


# ── REST: POST candle ─────────────────────────────────────────────────────────

@router.post(
    "/candles",
    response_model=ApiResponse[CandleResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_candle(
    candle: CandleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
):
    """
    Manually insert a candle (useful for testing or backfilling).
    The ticker must be quoted in USD — a manual insert has no FX rate to convert with.
    """
    db_candle = Candle(**candle.model_dump(), quote_currency="USD")
    db.add(db_candle)
    await db.commit()
    await db.refresh(db_candle)

    # Who inserted a price matters: every active user can do this, and the
    # numbers are the product (see the admin-role item in the security audit).
    logger.info(
        f"Candle inserted manually by user {user.id}: "
        f"{db_candle.exchange} {db_candle.ticker} {db_candle.interval} @ {db_candle.timestamp}"
    )

    return ApiResponse(
        status="success",
        message="Candle created successfully",
        data=CandleResponse.model_validate(db_candle),
    )


# ── WebSocket: live candles from Kafka ───────────────────────────────────────

async def _resolve_topics(db: AsyncSession, ticker: str, exchange: Optional[str] = None) -> List[str]:
    """
    Kafka topics carrying `ticker` — one per enabled exchange (optionally just
    `exchange`) that has an enabled market for it, according to the database.
    Empty for unknown or unsupported markets.

    The candidate source tickers are filtered in SQL. This previously loaded
    every enabled symbol row and compared unified tickers in Python, so each
    WebSocket connection scanned the whole symbols⋈exchanges join.
    """
    try:
        unified = unified_ticker(ticker)
        candidates = source_ticker_candidates(unified)
    except ValueError:
        return []

    query = (
        select(Exchange.name)
        .join(Symbol, Symbol.exchange_id == Exchange.id)
        .where(Exchange.enabled == True, Symbol.enabled == True)  # noqa: E712
        .where(Symbol.ticker.in_(candidates))
        .distinct()
    )
    if exchange:
        query = query.where(Exchange.name == exchange.lower())

    result = await db.execute(query)
    names = sorted(result.scalars().all())
    return [f"{name}.{topic_ticker(unified)}.candles" for name in names]


def _admit(key: str) -> tuple[bool, str]:
    """Take a connection slot, or explain why not. Caller must call _release."""
    global _open_connections

    if _open_connections >= WS_MAX_CONNECTIONS:
        return False, "server_capacity"
    if _connections_per_ip.get(key, 0) >= WS_MAX_CONNECTIONS_PER_IP:
        return False, "per_client_capacity"

    _open_connections += 1
    _connections_per_ip[key] = _connections_per_ip.get(key, 0) + 1
    return True, ""


def _release(key: str) -> None:
    global _open_connections

    _open_connections = max(_open_connections - 1, 0)
    remaining = _connections_per_ip.get(key, 0) - 1
    if remaining > 0:
        _connections_per_ip[key] = remaining
    else:
        _connections_per_ip.pop(key, None)


@router.websocket("/ws/live/{ticker}")
async def live_candles(
    websocket: WebSocket,
    ticker: str,
    exchange: Optional[str] = None,
    interval: Optional[str] = None,
    currency: Optional[str] = None,
):
    """
    WebSocket endpoint — streams live candles for a ticker in real time.

    Connect:  ws://localhost:8000/api/v1/market/ws/live/BTCUSD
    Optional: ?exchange=binance  — one exchange only
              ?interval=1m       — one candle length only (filtered server-side)
              ?currency=PLN      — prices in PLN (ECB daily rate), default USD

    BTCUSD, BTCUSDT and BTC-USDT all subscribe to the unified BTC/USD market.
    Each message is a unified-format candle (USD prices as 8-decimal strings),
    identical for every exchange.

    Close codes: 1008 unknown market (permanent — don't retry),
                 1013 at capacity or rate-limited (temporary — retry later).

    Subscribers share one Kafka consumer per topic (app/kafka/stream_hub.py),
    so a thousand viewers of one market cost one consumer, not a thousand.
    """
    client = client_key(websocket)

    allowed, retry_after = check_websocket_connect(websocket)
    if not allowed:
        websocket_connections_rejected_total.labels(reason="rate_limited").inc()
        await websocket.close(code=WS_TRY_AGAIN_LATER, reason=f"Rate limited; retry in {retry_after}s")
        return

    admitted, refusal = _admit(client)
    if not admitted:
        websocket_connections_rejected_total.labels(reason=refusal).inc()
        logger.warning(f"Live stream refused ({refusal}) — {_open_connections} open")
        await websocket.close(code=WS_TRY_AGAIN_LATER, reason="Too many live connections")
        return

    subscription = None
    try:
        await websocket.accept()

        # Short-lived session — don't hold a pooled DB connection for the socket's lifetime.
        async with AsyncSessionLocal() as db:
            topics = await _resolve_topics(db, ticker, exchange)

        if not topics:
            # Deliberately not echoing the client's raw ticker back.
            websocket_connections_rejected_total.labels(reason="unknown_market").inc()
            logger.debug(f"WebSocket rejected — no enabled market (exchange={exchange})")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unknown market")
            return

        wanted_interval = None
        if interval:
            try:
                wanted_interval = validate_interval(interval)
            except ValueError:
                websocket_connections_rejected_total.labels(reason="unknown_interval").inc()
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unsupported interval")
                return

        wanted_currency = "USD"
        if currency:
            try:
                wanted_currency = validate_currency(currency)
            except ValueError:
                websocket_connections_rejected_total.labels(reason="unknown_currency").inc()
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unsupported currency")
                return
            await fiat_rates.ensure_fresh()

        websocket_active_connections.labels(endpoint="live_candles").inc()
        # DEBUG, not INFO: this endpoint is unauthenticated, so an anonymous
        # client could otherwise drive unbounded log volume into Loki.
        logger.debug(f"WebSocket connected — topics: {topics}")

        subscription = await stream_hub.subscribe(topics)
        await _pump(websocket, subscription, wanted_interval, wanted_currency)

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as error:
        logger.error(f"WebSocket error: {error!r}")
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass        # already closed
    finally:
        if subscription is not None:
            websocket_active_connections.labels(endpoint="live_candles").dec()
            await stream_hub.unsubscribe(subscription)
        _release(client)


async def _pump(
    websocket: WebSocket, subscription, wanted_interval: Optional[str], currency: str = "USD",
) -> None:
    """
    Forward candles to the socket, with a heartbeat.

    The heartbeat is what reclaims a half-open connection: without traffic in
    either direction, a client that vanished without a close frame held its
    slot against the connection cap indefinitely.
    """
    while True:
        try:
            payload = await asyncio.wait_for(subscription.queue.get(), timeout=WS_HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            # Quiet market — prove the socket is still alive. Raises if it isn't.
            await websocket.send_json({"type": "heartbeat"})
            continue

        if wanted_interval and payload.get("interval") != wanted_interval:
            continue
        if currency != "USD":
            await fiat_rates.ensure_fresh()     # no-op until the cache's TTL runs out
            try:
                payload = convert_live(payload, currency, fiat_rates)
            except RateUnavailableError:
                # Never send a USD price labelled as something else; skip until a rate exists.
                logger.debug(f"No {currency} rate for a live candle — not sent")
                continue
        await websocket.send_json(payload)
