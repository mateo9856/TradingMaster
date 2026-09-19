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

eod_job_duration_seconds = Histogram(
    "eod_job_duration_seconds",
    "Duration of the EOD archive job",
)

eod_job_runs_total = Counter(
    "eod_job_runs_total",
    "Number of EOD archive job runs",
    ["status"],
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
