from datetime import date
from unittest.mock import MagicMock, patch

from app import eod_runner


def test_main_with_no_args_runs_eod_job_with_no_target_date():
    mock_run_eod_job = MagicMock(return_value=MagicMock())
    with (
        patch.object(eod_runner, "asyncio") as mock_asyncio,
        patch.object(eod_runner, "run_eod_job", mock_run_eod_job),
        patch.object(eod_runner.sys, "argv", ["eod_runner.py"]),
    ):
        eod_runner.main()

    mock_run_eod_job.assert_called_once_with(None)
    mock_asyncio.run.assert_called_once_with(mock_run_eod_job.return_value)


def test_main_with_date_arg_backfills_that_date():
    mock_run_eod_job = MagicMock(return_value=MagicMock())
    with (
        patch.object(eod_runner, "asyncio") as mock_asyncio,
        patch.object(eod_runner, "run_eod_job", mock_run_eod_job),
        patch.object(eod_runner.sys, "argv", ["eod_runner.py", "2026-06-23"]),
    ):
        eod_runner.main()

    mock_run_eod_job.assert_called_once_with(date(2026, 6, 23))
    mock_asyncio.run.assert_called_once_with(mock_run_eod_job.return_value)
