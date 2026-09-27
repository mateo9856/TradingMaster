"""
Environment-driven configuration.

Settings that are unsafe to get wrong are validated at import time by
validate_config() at the bottom of this file, which refuses to start a
production deployment on a development default rather than silently signing
real sessions with a key that is published in this repository.
"""

from dotenv import load_dotenv
import os

load_dotenv()

# Which kind of deployment this is: "development" (the default, permissive) or
# "production" (strict — see validate_config below). Staging and anything else
# that faces a real network should set "production".
APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION: bool = APP_ENV == "production"

# Database
TIMESCALE_URL: str = os.getenv("TIMESCALE_URL", "postgresql+asyncpg://user:mysecretpassword@localhost:5432/tradingmaster")

# Schema is owned by Alembic (`alembic upgrade head`), not by create_all at
# startup — see app/models/schema_check.py. The API verifies the database is at
# head and refuses to start otherwise. Turn this off only for a throwaway
# database whose schema you are building some other way (the test suite does).
DB_SCHEMA_CHECK: bool = os.getenv("DB_SCHEMA_CHECK", "true").lower() == "true"

# Kafka
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# Markets (exchanges + trading pairs + intervals) are NOT configured here — they
# live in the `exchanges` / `symbols` tables (seeded by app/models/seeder.py,
# managed through /api/v1/exchanges). The producer re-reads them every
# PRODUCER_CONFIG_REFRESH_SECONDS, so API changes apply without a restart.
# 0 disables the refresh (config is read once at startup).
PRODUCER_CONFIG_REFRESH_SECONDS: int = int(os.getenv("PRODUCER_CONFIG_REFRESH_SECONDS", "60"))

# Unified feed: every price is published in USD. USDT/USDC-quoted markets are
# converted with live USDT/USD and USDC/USD rates from this exchange; a rate
# older than FX_MAX_AGE_SECONDS (or none yet) falls back to the 1:1 peg.
FX_REFERENCE_EXCHANGE: str = os.getenv("FX_REFERENCE_EXCHANGE", "kraken")
FX_MAX_AGE_SECONDS: int = int(os.getenv("FX_MAX_AGE_SECONDS", "300"))

# Exchange API keys — optional, only needed for private/trading endpoints
# Public candle/ticker streams work without keys
EXCHANGE_CREDENTIALS: dict = {
    "binance":  {"apiKey": os.getenv("BINANCE_API_KEY", ""),  "secret": os.getenv("BINANCE_API_SECRET", "")},
    "kraken":   {"apiKey": os.getenv("KRAKEN_API_KEY", ""),   "secret": os.getenv("KRAKEN_API_SECRET", "")},
    "coinbase": {"apiKey": os.getenv("COINBASE_API_KEY", ""), "secret": os.getenv("COINBASE_API_SECRET", "")},
}

# Front-end: browser origins allowed to call the API cross-origin. Only needed
# when the UI is served separately (nginx container / another host) — the Vite
# dev proxy and the FastAPI-served production bundle are same-origin.
#
# The default is the Vite dev server, and *only* outside production: the CSRF
# defence in app/auth/csrf.py relies on a cross-origin page being unable to win
# a preflight, so whatever is listed here can also send authenticated writes.
# Leaving localhost trusted in production would have been a silent hole.
_DEFAULT_CORS_ORIGINS = "" if IS_PRODUCTION else "http://localhost:5173,http://127.0.0.1:5173"
CORS_ALLOW_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

# API limits. Both `limit` parameters used to be plain ints with no ceiling, so
# a single request could ask the database for every row it holds.
MARKET_MAX_PAGE_SIZE: int = int(os.getenv("MARKET_MAX_PAGE_SIZE", "1000"))
HISTORY_MAX_PAGE_SIZE: int = int(os.getenv("HISTORY_MAX_PAGE_SIZE", "10000"))
# Longest date span one history request may cover, in days.
HISTORY_MAX_RANGE_DAYS: int = int(os.getenv("HISTORY_MAX_RANGE_DAYS", "366"))

# Live WebSocket stream. Every viewer used to open its own Kafka consumer, so
# cost scaled with viewers rather than with markets; app/kafka/stream_hub.py now
# shares one consumer per topic. These cap what a single process will carry.
WS_MAX_CONNECTIONS: int = int(os.getenv("WS_MAX_CONNECTIONS", "500"))
WS_MAX_CONNECTIONS_PER_IP: int = int(os.getenv("WS_MAX_CONNECTIONS_PER_IP", "10"))
# Messages buffered per subscriber before the slowest ones start being dropped.
WS_QUEUE_MAXSIZE: int = int(os.getenv("WS_QUEUE_MAXSIZE", "250"))
# Ping interval. Without it, half-open sockets sat against the cap forever.
WS_HEARTBEAT_SECONDS: int = int(os.getenv("WS_HEARTBEAT_SECONDS", "30"))

# Rate limiting — in-process, per pod. With several replicas the effective
# limit is roughly this value times the replica count, which is fine for abuse
# protection; exact global limits would need shared state (e.g. Redis).
RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_READ_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_READ_PER_MINUTE", "300"))
RATE_LIMIT_WRITE_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_WRITE_PER_MINUTE", "60"))
# Deliberately strict: this is the brute-force ceiling on login, registration
# and password-reset, none of which had any limit at all before.
RATE_LIMIT_AUTH_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_AUTH_PER_MINUTE", "10"))
RATE_LIMIT_WS_CONNECT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_WS_CONNECT_PER_MINUTE", "30"))
# The archive trigger starts a full table scan + Parquet write per call.
RATE_LIMIT_ARCHIVE_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_ARCHIVE_PER_MINUTE", "5"))

# Honour X-Forwarded-For when working out a client's address. Only enable this
# behind a proxy that overwrites the header — otherwise any client can forge it
# and step around every per-IP limit above.
TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"

# Interactive API docs (/docs, /redoc, /openapi.json). On by default because
# this is a public data API; the production overlay turns them off.
DOCS_ENABLED: bool = os.getenv("DOCS_ENABLED", "true").lower() == "true"

# Observability — metrics
PROMETHEUS_METRICS_ENABLED: bool = os.getenv("PROMETHEUS_METRICS_ENABLED", "true").lower() == "true"

# Observability — tracing
OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower() == "true"
OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "tradingmaster-api")

# Observability — logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Auth — JWT signing for FastAPI Users.
#
# The development fallback is a literal published in this repository, so it is
# public knowledge: anyone can mint a valid session token with it. It stays for
# local convenience, but validate_config() refuses to start a production
# deployment that is still using it, or one that supplies an empty value —
# note that `os.getenv` returns "" (not None) for `AUTH_SECRET: ""`, which is
# exactly what the production Kubernetes secret template ships.
DEV_AUTH_SECRET = "dev-insecure-secret-change-me-in-every-real-deployment"
AUTH_SECRET: str = os.getenv("AUTH_SECRET", "").strip() or DEV_AUTH_SECRET

# Separate signing keys per token purpose, so a leaked password-reset token
# cannot be replayed as a session (and vice versa). Each falls back to
# AUTH_SECRET with a purpose label mixed in rather than reusing it verbatim.
AUTH_RESET_SECRET: str = os.getenv("AUTH_RESET_SECRET", "").strip() or f"{AUTH_SECRET}:reset"
AUTH_VERIFY_SECRET: str = os.getenv("AUTH_VERIFY_SECRET", "").strip() or f"{AUTH_SECRET}:verify"

AUTH_TOKEN_LIFETIME_SECONDS: int = int(os.getenv("AUTH_TOKEN_LIFETIME_SECONDS", "3600"))

# Browser sessions ride in an http-only cookie the page's JavaScript cannot read
# (see app/auth/backend.py); API clients keep using `Authorization: Bearer`.
AUTH_COOKIE_NAME: str = os.getenv("AUTH_COOKIE_NAME", "tradingmaster_auth")
# `Secure` means "HTTPS only" — the browser would then drop the cookie on a
# plain-http localhost, so the dev default is false. Like AUTH_SECRET, this must
# be overridden (AUTH_COOKIE_SECURE=true) in every real deployment.
AUTH_COOKIE_SECURE: bool = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"

# ── Startup validation ───────────────────────────────────────────────────────

class ConfigError(RuntimeError):
    """A production deployment is configured in a way that is unsafe to run."""


def validate_config() -> None:
    """
    Fail fast on a production deployment that still carries development
    defaults. Every one of these used to fail *open*: the app started happily
    and only the consequences showed up later.

    Runs at import time; set APP_ENV=development (the default) to skip.
    """
    if not IS_PRODUCTION:
        return

    problems: list[str] = []

    if AUTH_SECRET == DEV_AUTH_SECRET:
        problems.append(
            "AUTH_SECRET is unset or still the development default, which is published "
            "in this repository — anyone could forge a session. Generate one with: "
            "python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    elif len(AUTH_SECRET) < 32:
        problems.append(
            f"AUTH_SECRET is only {len(AUTH_SECRET)} characters; use at least 32."
        )

    if not AUTH_COOKIE_SECURE:
        problems.append(
            "AUTH_COOKIE_SECURE is false, so the session cookie would be sent over "
            "plain HTTP. Set AUTH_COOKIE_SECURE=true."
        )

    if "*" in CORS_ALLOW_ORIGINS:
        problems.append(
            "CORS_ALLOW_ORIGINS contains '*' while credentials are allowed. Any site "
            "could then make authenticated requests — list explicit origins instead."
        )

    for origin in CORS_ALLOW_ORIGINS:
        if origin.startswith("http://") and "localhost" not in origin and "127.0.0.1" not in origin:
            problems.append(
                f"CORS_ALLOW_ORIGINS contains the plain-http origin {origin!r}; use https."
            )

    if problems:
        raise ConfigError(
            "Refusing to start with an unsafe production configuration:\n  - "
            + "\n  - ".join(problems)
        )


validate_config()
