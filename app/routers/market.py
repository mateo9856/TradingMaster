import json
import logging
from typing import List, Optional
from urllib.parse import unquote

from aiokafka import AIOKafkaConsumer
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.config import KAFKA_BOOTSTRAP_SERVERS
from app.helpers.intervals import SUPPORTED_INTERVALS
from app.helpers.markets import topic_ticker, unified_ticker
from app.metrics import websocket_active_connections
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
               500: {"description": "Internal server error"}
    },
)

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


# ── REST: market list ────────────────────────────────────────────────────────

@router.get("/markets", response_model=ApiResponse[List[MarketResponse]])
async def list_markets(db: AsyncSession = Depends(get_db)):
    """
    Markets currently collected, as the unified feed publishes them — one entry
    per unified ticker, with the exchanges feeding it and the intervals
    available. Public; this is what a UI's market picker is built from.
    """
    result = await db.execute(
        select(Exchange.name, Symbol.ticker, Symbol.interval)
        .join(Symbol, Symbol.exchange_id == Exchange.id)
        .where(Exchange.enabled == True, Symbol.enabled == True)  # noqa: E712
    )

    markets: dict[str, dict[str, set]] = {}
    for exchange_name, source_ticker, interval in result.all():
        if interval not in SUPPORTED_INTERVALS:
            continue
        try:
            unified = unified_ticker(source_ticker)
        except ValueError:
            continue   # legacy row the unified feed can't publish
        entry = markets.setdefault(unified, {"exchanges": set(), "intervals": set()})
        entry["exchanges"].add(exchange_name)
        entry["intervals"].add(interval)

    data = [
        MarketResponse(
            ticker=ticker,
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
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """
    Get historical candles for a ticker, in the unified format (USD prices).
    BTC/USDT, BTC/USD and BTCUSDT all resolve to the unified BTC/USD market.
    Optionally filter by exchange and interval.
    """
    ticker_upper = resolve_ticker(ticker)
 
    query = (
        select(Candle)
        .where(Candle.ticker == ticker_upper)
        .where(Candle.interval == interval)
        .order_by(Candle.timestamp.desc())
        .limit(limit)
    )
 
    if exchange:
        query = query.where(Candle.exchange == exchange.lower())
 
    result = await db.execute(query)
    candles = result.scalars().all()

    if not candles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticker {ticker_upper} nie został znaleziony w platformie danych.",
        )
 
    return ApiResponse(
        status="success",
        message=f"Found {len(candles)} candle(s) for {ticker_upper}",
        data=[CandleResponse.model_validate(c) for c in candles],
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
    """
    try:
        unified = unified_ticker(ticker)
    except ValueError:
        return []

    query = (
        select(Exchange.name, Symbol.ticker)
        .join(Symbol, Symbol.exchange_id == Exchange.id)
        .where(Exchange.enabled == True, Symbol.enabled == True)  # noqa: E712
    )
    if exchange:
        query = query.where(Exchange.name == exchange.lower())

    result = await db.execute(query)
    names = set()
    for name, source_ticker in result.all():
        try:
            if unified_ticker(source_ticker) == unified:
                names.add(name)
        except ValueError:
            continue
    return [f"{name}.{topic_ticker(unified)}.candles" for name in sorted(names)]


@router.websocket("/ws/live/{ticker}")
async def live_candles(
    websocket: WebSocket,
    ticker: str,
    exchange: Optional[str] = None,
):
    """
    WebSocket endpoint — streams live candles for a ticker in real time.

    Connect:  ws://localhost:8000/api/v1/market/ws/live/BTCUSD
    Optional: ws://localhost:8000/api/v1/market/ws/live/BTCUSD?exchange=binance

    BTCUSD, BTCUSDT and BTC-USDT all subscribe to the unified BTC/USD market.
    Each message is a unified-format candle (USD prices as 8-decimal strings),
    identical for every exchange. Unknown markets are closed with code 1008.
    """
    await websocket.accept()

    # Short-lived session — don't hold a pooled DB connection for the socket's lifetime.
    async with AsyncSessionLocal() as db:
        topics = await _resolve_topics(db, ticker, exchange)

    if not topics:
        logger.info(f"WebSocket rejected — no enabled market for {ticker} (exchange={exchange})")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=f"Unknown market {ticker}")
        return

    websocket_active_connections.labels(endpoint="live_candles").inc()
    logger.info(f"WebSocket client connected — topics: {topics}")

    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=None,          # None = no consumer group, always reads latest
        auto_offset_reset="latest",
    )

    try:
        await consumer.start()
        async for message in consumer:
            payload = json.loads(message.value.decode("utf-8"))
            await websocket.send_json(payload)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from {ticker}")

    except Exception as e:
        logger.error(f"WebSocket error for {ticker}: {e}")
        await websocket.close(code=1011)

    finally:
        websocket_active_connections.labels(endpoint="live_candles").dec()
        await consumer.stop()
