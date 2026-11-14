"""Export producer heartbeat and duplicate-start state from PostgreSQL."""

import logging
from datetime import timezone

from sqlalchemy import select

from app.metrics import (
    producer_duplicate_starts_total,
    producer_last_heartbeat_timestamp_seconds,
)
from app.models.database import AsyncSessionLocal
from app.models.producer_status import ProducerStatus

logger = logging.getLogger(__name__)


async def refresh_producer_metrics() -> None:
    try:
        async with AsyncSessionLocal() as db:
            status = await db.scalar(select(ProducerStatus).where(ProducerStatus.id == 1))
    except Exception as error:
        logger.warning("Could not refresh producer metrics: %r", error)
        return

    if status is None:
        producer_last_heartbeat_timestamp_seconds.set(0)
        producer_duplicate_starts_total.set(0)
        return

    heartbeat = status.heartbeat_at
    producer_last_heartbeat_timestamp_seconds.set(
        heartbeat.replace(tzinfo=timezone.utc).timestamp() if heartbeat else 0
    )
    producer_duplicate_starts_total.set(status.duplicate_starts)
