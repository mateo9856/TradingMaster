"""
The EOD runner's CLI.

main() returns an exit code rather than letting an exception escape, because
the Kubernetes CronJob's backoffLimit reacts to it: a genuine failure should
retry, but losing the race for the advisory lock should not.
"""

from datetime import date
from unittest.mock import patch

import pytest

from app import eod_runner
from app.jobs.eod_archive import ArchiveLockedError, ArchiveResult


def _result(target=date(2026, 6, 23)):
    return ArchiveResult(target_date=target, inserted=1)


def test_no_arguments_archives_yesterday():
    with patch.object(eod_runner, "run_eod_job") as job, \
         patch.object(eod_runner.asyncio, "run", side_effect=lambda coro: (coro.close(), _result())[1]):
        assert eod_runner.main([]) == eod_runner.EXIT_OK

    job.assert_called_once_with(None, replace=False, dry_run=False)


def test_date_argument_backfills_that_date():
    with patch.object(eod_runner, "run_eod_job") as job, \
         patch.object(eod_runner.asyncio, "run", side_effect=lambda coro: (coro.close(), _result())[1]):
        assert eod_runner.main(["2026-06-23"]) == eod_runner.EXIT_OK

    job.assert_called_once_with(date(2026, 6, 23), replace=False, dry_run=False)


def test_flags_are_passed_through():
    with patch.object(eod_runner, "run_eod_job") as job, \
         patch.object(eod_runner.asyncio, "run", side_effect=lambda coro: (coro.close(), _result())[1]):
        assert eod_runner.main(["2026-06-23", "--replace", "--dry-run"]) == eod_runner.EXIT_OK

    job.assert_called_once_with(date(2026, 6, 23), replace=True, dry_run=True)


def test_an_invalid_date_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        eod_runner.main(["not-a-date"])


def test_a_failed_run_exits_non_zero():
    with patch.object(eod_runner, "run_eod_job"), \
         patch.object(eod_runner.asyncio, "run", side_effect=RuntimeError("boom")):
        assert eod_runner.main(["2026-06-23"]) == eod_runner.EXIT_FAILED


def test_losing_the_lock_is_not_reported_as_a_failure():
    """
    The CronJob and a manual backfill can legitimately overlap. Exiting 1 there
    would burn the CronJob's backoffLimit retries and raise a false alert, when
    the other run is already doing the work.
    """
    with patch.object(eod_runner, "run_eod_job"), \
         patch.object(eod_runner.asyncio, "run", side_effect=ArchiveLockedError("already running")):
        assert eod_runner.main(["2026-06-23"]) == eod_runner.EXIT_LOCKED
