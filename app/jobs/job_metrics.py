"""
Exports the EOD archive's outcome to Prometheus from the `job_runs` table.

The job's own counters live in whichever process ran it, and the scheduled run
is a short-lived CronJob pod with no /metrics endpoint — nothing ever scraped
them, so the archive was effectively unmonitored. The API is the only process
Prometheus scrapes, so it refreshes these gauges from the database on each
scrape instead.
"""

import logging

from datetime import timezone

from sqlalchemy import select

from app.metrics import eod_last_success_timestamp_seconds
from app.models.database import AsyncSessionLocal
from app.models.job_run import EOD_ARCHIVE_JOB, STATUS_SUCCESS, JobRun

logger = logging.getLogger(__name__)


async def refresh_job_metrics() -> None:
    """
    Update the archive gauges from the most recent successful run.

    Best-effort, and it opens its own session: **everything** here is inside the
    try, connection included. A scrape must never fail because the database is
    unreachable — that would take every other metric the process exports down
    with it, exactly when monitoring is most needed.
    """
    try:
        async with AsyncSessionLocal() as db:
            last_success = await db.scalar(
                select(JobRun.finished_at)
                .where(JobRun.job_name == EOD_ARCHIVE_JOB)
                .where(JobRun.status == STATUS_SUCCESS)
                .where(JobRun.finished_at.is_not(None))
                .order_by(JobRun.finished_at.desc())
                .limit(1)
            )
    except Exception as error:
        logger.warning(f"Could not refresh archive job metrics: {error!r}")
        return

    if last_success is not None:
        # Stored naive but in UTC (see app/helpers/time.py).
        eod_last_success_timestamp_seconds.set(
            last_success.replace(tzinfo=timezone.utc).timestamp()
        )
