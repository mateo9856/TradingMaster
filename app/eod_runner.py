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
    python -m app.eod_runner                        # archives yesterday (UTC)
    python -m app.eod_runner 2026-06-23             # backfill a specific date
    python -m app.eod_runner 2026-06-23 --dry-run   # report, change nothing
    python -m app.eod_runner 2026-06-23 --replace   # discard and re-archive the day

Re-running a date is safe: the archive skips rows history already holds. Use
--replace only to re-archive after correcting source data.

Exit codes: 0 success, 1 failure, 2 another run holds the lock,
            3 --replace refused (the day's source candles are gone).
"""

import argparse
import asyncio
import logging
import sys
from datetime import date

import app.config as config
from app.jobs.eod_archive import ArchiveLockedError, NothingToReplaceError, run_eod_job
from app.logging_config import setup_json_logging
from app.tracing import setup_tracing

setup_json_logging(service="tradingmaster-eod", level=getattr(logging, config.LOG_LEVEL, logging.INFO))
setup_tracing(
    "tradingmaster-eod",
    config.OTEL_EXPORTER_OTLP_ENDPOINT,
    enabled=config.OTEL_ENABLED,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOCKED = 2
EXIT_REFUSED = 3


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.eod_runner",
        description="Archive one day of candles to history + Parquet.",
    )
    parser.add_argument(
        "target_date", nargs="?", type=date.fromisoformat, default=None,
        metavar="YYYY-MM-DD", help="day to archive (default: yesterday, UTC)",
    )
    parser.add_argument(
        "--replace", action="store_true",
        help="delete the day's existing history rows and re-archive it "
             "(only needed after correcting source data — a plain re-run is already safe)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be archived without changing anything",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = asyncio.run(
            run_eod_job(args.target_date, replace=args.replace, dry_run=args.dry_run)
        )
    except ArchiveLockedError as error:
        # Not a failure: the CronJob and a manual backfill can legitimately
        # overlap, and the other run is doing the work.
        logger.warning(str(error))
        return EXIT_LOCKED
    except NothingToReplaceError as error:
        logger.error(str(error))
        return EXIT_REFUSED
    except Exception:
        logger.exception("EOD archive job failed")
        return EXIT_FAILED

    logger.info(
        f"EOD archive finished for {result.target_date}: "
        f"{result.inserted} archived, {result.skipped_duplicate} already present, "
        f"{result.files_written} file(s) written, {result.deleted} cleaned up"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
