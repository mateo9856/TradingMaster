"""
Prometheus metric collectors, shared across the FastAPI app.

Collectors are module-level singletons. Importing this module multiple times
(e.g. from several test modules) is safe because Python only executes module
bodies once — do NOT move these into a function, as re-invoking prometheus_client's
Counter()/Gauge()/Histogram() constructors against the default registry raises
ValueError: Duplicated timeseries in CollectorRegistry.
"""

from prometheus_client import Counter, Gauge, Histogram

kafka_messages_produced_total = Counter(
    "kafka_messages_produced_total",
    "Number of candle messages produced to Kafka",
    ["exchange", "ticker", "interval"],
)

kafka_reconnects_total = Counter(
    "kafka_reconnects_total",
    "Number of exchange stream reconnects after an error",
    ["exchange"],
)

websocket_active_connections = Gauge(
    "websocket_active_connections",
    "Number of currently open live-candle WebSocket connections",
    ["endpoint"],
)

websocket_connections_rejected_total = Counter(
    "websocket_connections_rejected_total",
    "Live-stream connections refused, by reason (cap reached, unknown market, rate limit)",
    ["reason"],
)

websocket_messages_dropped_total = Counter(
    "websocket_messages_dropped_total",
    "Candles dropped because a live-stream subscriber could not keep up",
)

# One consumer per *topic being watched*, shared by every subscriber — so this
# tracks markets under observation, not viewers. It used to be one consumer per
# viewer (see app/kafka/stream_hub.py).
stream_hub_consumers = Gauge(
    "stream_hub_consumers",
    "Kafka consumers the live-stream hub is currently running (one per watched topic)",
)

stream_hub_subscribers = Gauge(
    "stream_hub_subscribers",
    "Live-stream subscriptions attached to the hub (a viewer counts once per topic)",
)

rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total",
    "Requests rejected with 429 by the in-process rate limiter",
    ["bucket"],
)

# Explicit buckets: a real archive run takes minutes, and the prometheus_client
# default buckets top out at 10s, so every run landed in +Inf and the p95 panel
# was meaningless.
eod_job_duration_seconds = Histogram(
    "eod_job_duration_seconds",
    "Duration of the EOD archive job",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)

eod_job_runs_total = Counter(
    "eod_job_runs_total",
    "Number of EOD archive job runs",
    ["status"],
)

# Without this, the "failure" series does not exist in the registry until the
# first failure ever happens — so alert expressions using absent() or a
# success/failure ratio silently never fire.
for _status in ("success", "failure", "skipped"):
    eod_job_runs_total.labels(status=_status)

eod_last_success_timestamp_seconds = Gauge(
    "eod_last_success_timestamp_seconds",
    "Unix timestamp of the last successful EOD archive run "
    "(exported by the API from the job_runs table — the scheduled job runs in "
    "its own short-lived pod that Prometheus never scrapes)",
)

eod_rows_archived_total = Counter(
    "eod_rows_archived_total",
    "Candle rows written to candles_history by the EOD archive job",
)

eod_rows_skipped_duplicate_total = Counter(
    "eod_rows_skipped_duplicate_total",
    "Candle rows the EOD archive job skipped because history already had them "
    "(a re-run or a retry of an already-archived day)",
)

eod_rows_deleted_total = Counter(
    "eod_rows_deleted_total",
    "Candle rows deleted from the hot table by the EOD archive job's retention cleanup",
)

eod_parquet_files_written_total = Counter(
    "eod_parquet_files_written_total",
    "Parquet archive files written by the EOD archive job",
)

eod_parquet_skipped_total = Counter(
    "eod_parquet_skipped_total",
    "EOD archive runs that produced no Parquet file because pandas/pyarrow were missing",
)

http_requests_total = Counter(
    "http_requests_total",
    "Number of HTTP requests handled",
    ["method", "path", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

fx_rate = Gauge(
    "fx_rate",
    "Latest live rate used to convert a quote currency to USD",
    ["quote"],
)

fx_rate_fallback_total = Counter(
    "fx_rate_fallback_total",
    "Number of conversions that used the 1:1 USD peg because no fresh live rate was available",
    ["quote"],
)

candles_skipped_total = Counter(
    "candles_skipped_total",
    "Number of exchange candles dropped because they could not be converted to the unified format",
    ["exchange"],
)
