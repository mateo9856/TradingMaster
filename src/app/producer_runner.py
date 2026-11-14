"""Run the singleton Kafka producer outside the horizontally scaled API."""

import asyncio
import logging
import uuid

from prometheus_client import start_http_server
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.config as config
from app.fiat.rates import fiat_rates, watch_fiat_rates
from app.helpers.time import utc_now_naive
from app.kafka.producer import run_producer
from app.kafka.producer_lock import producer_advisory_lock
from app.logging_config import setup_json_logging
from app.models.database import AsyncSessionLocal, engine
from app.models.producer_status import ProducerStatus
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-producer", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
setup_tracing(
    "tradingmaster-producer",
    config.OTEL_EXPORTER_OTLP_ENDPOINT,
    enabled=config.OTEL_ENABLED,
)

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30
RETRY_SECONDS = 15


def _insert_status(db: AsyncSession):
    if db.bind.dialect.name == "sqlite":
        return sqlite_insert(ProducerStatus)
    return pg_insert(ProducerStatus)


async def record_active_instance(
    instance_id: str,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> None:
    now = utc_now_naive()
    async with session_factory() as db:
        insert = _insert_status(db).values(
            id=1, instance_id=instance_id, started_at=now, heartbeat_at=now, duplicate_starts=0
        )
        await db.execute(insert.on_conflict_do_update(
            index_elements=[ProducerStatus.id],
            set_={
                "instance_id": insert.excluded.instance_id,
                "started_at": insert.excluded.started_at,
                "heartbeat_at": insert.excluded.heartbeat_at,
            },
        ))
        await db.commit()


async def record_duplicate_start(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> None:
    async with session_factory() as db:
        insert = _insert_status(db).values(id=1, duplicate_starts=1)
        await db.execute(insert.on_conflict_do_update(
            index_elements=[ProducerStatus.id],
            set_={"duplicate_starts": ProducerStatus.duplicate_starts + 1},
        ))
        await db.commit()


async def _heartbeat(
    instance_id: str,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        async with session_factory() as db:
            await db.execute(
                update(ProducerStatus)
                .where(ProducerStatus.id == 1, ProducerStatus.instance_id == instance_id)
                .values(heartbeat_at=utc_now_naive())
            )
            await db.commit()


async def main() -> None:
    if config.PROMETHEUS_METRICS_ENABLED:
        start_http_server(config.PRODUCER_METRICS_PORT, addr="0.0.0.0")

    while True:
        instance_id = str(uuid.uuid4())
        async with producer_advisory_lock(engine) as acquired:
            if not acquired:
                await record_duplicate_start()
                logger.error("Another producer holds the singleton lock; retrying after a delay")
            else:
                await record_active_instance(instance_id)
                logger.info("Producer instance acquired the singleton lock", extra={"instance_id": instance_id})
                heartbeat_task = asyncio.create_task(_heartbeat(instance_id))
                fiat_task = asyncio.create_task(watch_fiat_rates(fiat_rates))
                try:
                    await run_producer()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Producer exited unexpectedly; retrying")
                finally:
                    heartbeat_task.cancel()
                    fiat_task.cancel()
                    await asyncio.gather(heartbeat_task, fiat_task, return_exceptions=True)

        await asyncio.sleep(RETRY_SECONDS if acquired else HEARTBEAT_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
