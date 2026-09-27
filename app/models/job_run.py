"""
One row per background-job run — currently the EOD archive.

Why this table exists: the archive's Prometheus counters live in whichever
process ran the job, and the scheduled job is a short-lived CronJob pod with no
/metrics endpoint for Prometheus to scrape. Its metrics were therefore never
collected at all; only the manual API-triggered path was ever visible.

Recording the outcome in the database instead means the API can export it
(app/metrics.py reads the latest rows), the UI can show archive health, and
there is a durable audit trail of what ran, when, and with what result.
"""

from sqlalchemy import Column, Date, DateTime, Index, Integer, String, Text

from .database import Base
from app.helpers.time import utc_now_naive

# Status values written to JobRun.status
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
# The run was rejected before doing anything (e.g. --replace for a day whose
# source candles are gone). Kept apart from "failure" so it doesn't raise the
# EodJobFailed alert — nothing is broken, the request was simply refused.
STATUS_REFUSED = "refused"

EOD_ARCHIVE_JOB = "eod_archive"


class JobRun(Base):
    __tablename__ = "job_runs"

    id          = Column(Integer, primary_key=True, index=True)
    job_name    = Column(String(64), nullable=False)      # "eod_archive"
    target_date = Column(Date, nullable=True)             # the day being archived
    started_at  = Column(DateTime, nullable=False, default=utc_now_naive)
    finished_at = Column(DateTime, nullable=True)         # NULL while still running
    status      = Column(String(16), nullable=False, default=STATUS_RUNNING)
    rows_archived = Column(Integer, nullable=False, default=0)
    rows_skipped  = Column(Integer, nullable=False, default=0)   # already in history
    rows_deleted  = Column(Integer, nullable=False, default=0)   # aged out of the hot table
    files_written = Column(Integer, nullable=False, default=0)   # Parquet files
    error       = Column(Text, nullable=True)             # exception text on failure

    __table_args__ = (
        Index("ix_job_runs_job_name_started_at", "job_name", "started_at"),
    )
