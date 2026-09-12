"""
Standalone EOD (End-of-Day) archive job entry point.

Runs run_eod_job() once and exits — this replaces the asyncio scheduler loop
that used to live in app/main.py's lifespan. Being in-process there meant a
crashed/redeployed FastAPI process silently skipped that day's archive run,
with nothing outside the process aware it hadn't happened.

Instead, drive this with an external scheduler that survives API restarts:
  - host cron / systemd timer:  30 23 * * * python -m app.eod_runner
  - Kubernetes: see k8s/base/eod-cronjob.yaml (a CronJob, not a Deployment —
    this only needs to run once a day and exit; schedule defaults to 23:30 UTC
    and is overridable per overlay, see k8s/overlays/local/eod-patch.yaml)

For ad-hoc/backfill runs (not on the daily schedule), use the manual trigger
endpoint instead: POST /api/v1/history/archive/{target_date}

Run manually:
    source env/bin/activate
    python -m app.eod_runner              # archives yesterday (UTC)
    python -m app.eod_runner 2026-06-23   # backfill a specific date
"""

import asyncio
import logging
import sys
from datetime import date

import app.config as config
from app.jobs.eod_archive import run_eod_job
from app.logging_config import setup_json_logging
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-eod", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
setup_tracing(
    "tradingmaster-eod",
    config.OTEL_EXPORTER_OTLP_ENDPOINT,
    enabled=config.OTEL_ENABLED,
)

logger = logging.getLogger(__name__)


def main() -> None:
    target_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_eod_job(target_date))


if __name__ == "__main__":
    main()
