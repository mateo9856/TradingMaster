import json
import logging
from typing import List, Optional
from urllib.parse import unquote

from aiokafka import AIOKafkaConsumer
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import KAFKA_BOOTSTRAP_SERVERS
from app.models import CandleCreate, CandleResponse, ApiResponse, Candle
from app.models.database import get_db

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
    Get historical candles for a ticker.
    Optionally filter by exchange and interval.
    """
    # Clients may send symbols as either BTC/USDT or URL-encoded BTC%2FUSDT.
    ticker_upper = unquote(ticker).upper()
 
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
):
    """
    Manually insert a candle (useful for testing or backfilling).
    """
    db_candle = Candle(**candle.model_dump())
    db.add(db_candle)
    await db.commit()
    await db.refresh(db_candle)

    return ApiResponse(
        status="success",
        message="Candle created successfully",
        data=CandleResponse.model_validate(db_candle),
    )
 
 
# ── WebSocket: live candles from Kafka ───────────────────────────────────────
 
@router.websocket("/ws/live/{ticker}")
async def live_candles(
    websocket: WebSocket,
    ticker: str,
    exchange: Optional[str] = None,
):
    """
    WebSocket endpoint — streams live candles for a ticker in real time.
 
    Connect:  ws://localhost:8000/api/v1/market/ws/live/BTCUSDT
    Optional: ws://localhost:8000/api/v1/market/ws/live/BTCUSDT?exchange=binance
 
    Each message is a JSON object matching CandleResponse schema.
    """
    await websocket.accept()
    ticker_normalized = ticker.upper().replace("/", "")
 
    # Build list of Kafka topics to subscribe to
    # If exchange is specified, only listen to that exchange's topic
    if exchange:
        topics = [f"{exchange.lower()}.{ticker_normalized}.candles"]
    else:
        # Listen to all exchanges for this ticker
        from app.config import WATCH_EXCHANGES
        topics = [f"{ex}.{ticker_normalized}.candles" for ex in WATCH_EXCHANGES]
 
    logger.info(f"WebSocket client connected — topics: {topics}")
 
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=None,          # None = no consumer group, always reads latest
        auto_offset_reset="latest",
    )
 
    await consumer.start()
 
    try:
        async for message in consumer:
            payload = json.loads(message.value.decode("utf-8"))
            await websocket.send_json(payload)
 
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from {ticker_normalized}")
 
    except Exception as e:
        logger.error(f"WebSocket error for {ticker_normalized}: {e}")
        await websocket.close(code=1011)
 
    finally:
        await consumer.stop()
