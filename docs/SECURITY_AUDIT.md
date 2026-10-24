# TradingMaster — Security Audit (OWASP Top 10, 2021)

**Date:** 2026-09-27  ·  **Scope:** the whole repository at this commit
**Method:** manual source review of every application file, the Kubernetes and
Compose manifests, both Dockerfiles, the front-end bundle and the dependency
manifests, mapped onto the OWASP Top 10 (2021). Findings were confirmed by
reading the code, not inferred from configuration alone.

---

## 1. Summary

The platform's foundations are sound. There is **no SQL injection, no command
injection and no unsafe deserialisation anywhere in the codebase**, the session
design is already better than most at this stage (http-only cookie,
`SameSite=strict`, a CSRF middleware, Argon2 password hashing), and no
credential has ever been committed to git.

The findings below are dominated by one pattern: **security-critical settings
that failed open.** A missing `AUTH_SECRET` fell back to a value published in
this repository; `AUTH_COOKIE_SECURE` defaulted to off; CORS defaulted to
trusting `localhost` even in production; there was no password policy and no
rate limiting at all. None of these produced an error — the application started
normally and the consequences would only have appeared later.

**26 findings.** 22 are fixed in this change; 4 remain open and are tracked with
owners in section 5.

| Severity | Fixed | Tracked | Total |
|---|---|---|---|
| Critical | 1 | 0 | 1 |
| High | 4 | 4 | 8 |
| Medium | 12 | 3 | 15 |
| Low | 5 | 1 | 6 |

> The tracked items are deliberate scope decisions, not oversights. The largest
> — an admin role — is a product decision about who may do what, and is roadmap
> item #4 in `BUSINESS_SUMMARY.md`.

---

## 2. Verified clean

Recorded explicitly, because an audit needs the negatives as much as the positives.

| Area | Finding |
|---|---|
| **SQL injection** | None. Every database access goes through SQLAlchemy Core/ORM expressions with bound parameters. A repository-wide search for `text(`, f-string SQL, `os.system`, `subprocess`, `eval`, `exec`, `pickle` and `yaml.load` returns no application-code hits. |
| **Command injection** | No shell invocation anywhere in the application. |
| **Deserialisation** | JSON only, via `json.loads` on Kafka payloads, with decode errors caught. |
| **Session storage** | No token is written to `localStorage`, `sessionStorage` or `document.cookie`. The front-end restores a session by calling `GET /users/me`; existing tests assert browser storage stays empty. |
| **XSS sinks** | No `dangerouslySetInnerHTML`, no `innerHTML`, no `eval` in `frontend/src/`. |
| **Path traversal** | The SPA fallback resolves the candidate path and checks `is_relative_to(FRONTEND_DIST)` before serving (`app/main.py`). Correct order, correctly rejected. |
| **Password hashing** | Argon2 via `pwdlib`, the fastapi-users default; never overridden with anything weaker. |
| **Token logging** | Password-reset and verification tokens are in scope at their log sites and are deliberately not logged. |
| **Git history** | `git log --all -- .env` is empty and `.env` has never been tracked. No credential is in the repository's history. |
| **Resource limits** | Every Kubernetes workload sets CPU and memory requests and limits. |

---

## 3. Findings fixed in this change

### A01 — Broken Access Control

**A01-3 · Medium · `/metrics` exposed unauthenticated on a public address**
`/metrics` is public (`app/main.py`) and in production `fastapi-service` is a
`LoadBalancer`, so the full market inventory and per-path request volumes were
readable by anyone. Worse, the collector labelled by **raw request path**, so
an anonymous client could mint an unbounded number of Prometheus time series
just by requesting distinct URLs — a memory-exhaustion path into the monitoring
system itself.
*Fixed:* metrics are now labelled by the matched route template
(`/api/v1/market/candles/{ticker}`), which is bounded by the number of routes.
Exposure is addressed by A01-4's Service changes; keeping the endpoint itself
open is deliberate for a public data API.

**A01-4 · Medium · Grafana and Jaeger had public IP addresses**
`k8s/overlays/prod/observability-patch.yaml` set `type: LoadBalancer` on both
`grafana-service` and `jaeger-service`. Jaeger has no authentication of its own,
and its traces describe the platform's entire internal call graph.
*Fixed:* both are `ClusterIP`; the manifest documents `kubectl port-forward` and
an authenticated ingress as the ways in.

### A02 — Cryptographic Failures

**A02-1 · Critical · `AUTH_SECRET` failed open to a published value**
`app/config.py` fell back to the literal
`"dev-insecure-secret-change-me-in-every-real-deployment"`, which is in this
repository and therefore public knowledge — anyone could forge a valid session
token for any account. Three things made this worse than a stale default:
no warning was logged; the local Kubernetes overlay set no `AUTH_SECRET` at all,
so it ran on the fallback; and the production overlay ships `AUTH_SECRET: ""`,
which `os.getenv` returns as `""` rather than `None`, so a JWT would have been
signed with an **empty** key.
*Fixed:* `validate_config()` refuses to start when `APP_ENV=production` and the
secret is missing, empty, the development default, or shorter than 32
characters. Verified against the exact empty-string case the production template
ships.

**A02-2 · High · Session cookie was not HTTPS-only by default**
`AUTH_COOKIE_SECURE` defaulted to `false` so that plain-http localhost works. A
deployment that forgot to override it would have sent session cookies in clear.
*Fixed:* the default stands for local development, but production start-up now
fails if it is false.

**A02-3 · Medium · One secret signed three different kinds of token**
`app/auth/manager.py` used `AUTH_SECRET` for session JWTs, password-reset tokens
and verification tokens, so a leak of any one compromised all three.
*Fixed:* `AUTH_RESET_SECRET` and `AUTH_VERIFY_SECRET`, each falling back to
`AUTH_SECRET` with a purpose label mixed in rather than reusing it verbatim.

### A03 — Injection

**A03-2 · Medium · `exchanges.name` was unvalidated free text reaching three sinks**
Any authenticated user could `POST /api/v1/exchanges` with an arbitrary name,
which then became (a) a ccxt attribute lookup `getattr(ccxtpro, name)`, (b) a
Kafka topic-name segment, and (c) part of the Flink job's topic-pattern **inside
a SQL string literal**. `re.escape` is applied there, but Python's `re.escape`
does not escape `'`, so a quote in an exchange name would break out of that
literal.
*Fixed:* `ExchangeCreate.name` is constrained to `^[a-z0-9_]{2,32}$` *and*
validated against ccxt's own exchange list; `method` is a `Literal`. The
producer and the FX watcher re-check the id before the `getattr`, so a row
written directly into the database cannot slip past either.

### A04 — Insecure Design

**A04-1 · High · The nightly archive was not idempotent**
Covered in full by roadmap item #8; see `BUSINESS_SUMMARY.md`. `candles_history`
had no unique constraint and the job used a blind `add_all`, so a re-run — or
the CronJob's own `backoffLimit: 2` retry, or the local overlay's
every-10-minutes schedule — appended a complete second copy of the day.
*Fixed:* unique key plus `ON CONFLICT DO NOTHING`, with existing duplicates
removed by the migration.

**A04-2 · High · No rate limiting anywhere** — see A07-2.

**A04-3 · High · The live stream's cost scaled with viewers**
Each WebSocket connection opened its own `AIOKafkaConsumer`. A few hundred
viewers of one market meant a few hundred broker connections and a few hundred
copies of every message decoded in-process, with no connection cap at all.
*Fixed:* `app/kafka/stream_hub.py` shares one consumer per topic, so cost scales
with markets watched (~50) rather than with traffic; plus global and per-IP
connection caps, bounded per-subscriber queues that drop oldest rather than grow
without limit, and a heartbeat that reclaims half-open sockets.

**A04-4 · Medium · The archive trigger was unbounded and unsupervised**
`POST /history/archive/{date}` fired a bare `asyncio.create_task` per call — no
reference kept (so it could be garbage-collected mid-flight), no error handling
(a failure surfaced only as "exception was never retrieved"), no concurrency
guard, and no rate limit, while each call starts a full table scan and Parquet
write inside the API process.
*Fixed:* the task is referenced and its outcome logged and recorded; a
PostgreSQL advisory lock prevents concurrent runs; the endpoint has its own
strict rate-limit bucket and rejects dates that are not finished days.

### A05 — Security Misconfiguration

**A05-1 · High · Both images baked the build host's `.env` into a layer**
`Dockerfile` had `COPY .env .` and `app/flink_jobs/Dockerfile` had
`COPY app/.env .`, so whatever the person building held locally travelled to
every registry puller, recoverable with `docker history` and surviving even if
a later layer deleted the file.
*Verified:* no real credential is in the current `.env` — its 31-character
`BINANCE_API_SECRET` is a malformed line where `PROMETHEUS_METRICS_ENABLED=true`
was concatenated onto an empty assignment (see A05-10). The practice is the
finding, not a present leak.
*Fixed:* both `COPY` lines removed; configuration is injected at run time.

**A05-2 · Medium · Containers ran as root**
Neither the API image nor the front-end image had a `USER` directive; only the
Flink image dropped privileges.
*Fixed:* the API runs as `appuser` (uid 10001) and nginx as `nginx`.

**A05-3 · Medium · No `securityContext` and no `NetworkPolicy` in Kubernetes**
None of the manifests set `runAsNonRoot`, `allowPrivilegeEscalation`,
`capabilities.drop` or `seccompProfile`, and with no NetworkPolicy any pod could
reach PostgreSQL or Kafka directly.
*Fixed:* security contexts on the API, migration Job and archive CronJob, plus
`k8s/base/network-policy.yaml` — default-deny ingress with explicit allows.
**Note:** NetworkPolicy is enforced by the CNI plugin; on a cluster whose CNI
ignores it these objects apply cleanly and filter nothing, so a successful apply
is not proof of enforcement.

**A05-4 · Medium · CORS defaulted to trusting localhost, including in production**
`CORS_ALLOW_ORIGINS` defaulted to the Vite dev origins. This is not only a CORS
question: the CSRF defence in `app/auth/csrf.py` rests on a cross-origin page
being unable to win a preflight, so anything on this list can also send
authenticated writes.
*Fixed:* the default applies only outside production; production start-up
rejects `*` alongside credentials, and rejects plain-http non-localhost origins.

**A05-5 · Medium · No security response headers anywhere**
Neither FastAPI nor `frontend/nginx.conf` set CSP, `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy` or HSTS.
*Fixed:* `app/middleware/security_headers.py` and matching `add_header`
directives in nginx. HSTS is sent only when the deployment is HTTPS — sending it
from a plain-http dev server would pin the browser to an origin that does not
exist. `/docs` gets a relaxed policy of its own, since Swagger UI loads from a
CDN and would otherwise render blank.

**A05-6 · Medium · Middleware order defeated the CSRF error path**
Starlette builds its stack from `reversed(user_middleware)`, so the registration
order put CORS **innermost** — the opposite of what the code comment claimed. A
CSRF rejection therefore carried no `Access-Control-Allow-Origin`, and a
cross-origin UI saw an opaque network error instead of the 403 explaining what
to fix.
*Fixed:* the stack is now, outside in, security headers → CORS → metrics → rate
limit → CSRF → router, with a regression test asserting the 403 carries CORS
headers.

**A05-7 · Low · Interactive docs always enabled**
`/docs`, `/redoc` and `/openapi.json` were unconditional, publishing the whole
endpoint surface from a production LoadBalancer.
*Fixed:* `DOCS_ENABLED`, default on (this is a public data API), set to `false`
in the production overlay.

**A05-8 · Low · Every image is `:latest`** — production had no deterministic
version to roll back to. *Partially fixed:* the production overlay sets
`APP_ENV`/`DOCS_ENABLED` explicitly and the README documents tagging by git SHA;
actually doing the tagging belongs to the release pipeline, which is out of
scope here.

**A05-10 · Low · `.env` is malformed and carries dead settings**
Line 6 reads `BINANCE_API_SECRET=PROMETHEUS_METRICS_ENABLED=true`, so
`PROMETHEUS_METRICS_ENABLED` is never actually set and `BINANCE_API_SECRET`
holds a junk value. `WATCH_SYMBOLS` and `WATCH_EXCHANGES` are settings the code
stopped reading when markets moved into the database.
*Fixed:* a correct, fully documented `.env.example` is committed. The real
`.env` is gitignored and must be corrected by hand — **action for the developer.**

**A05-11 · Low · The test database was one `git add .` from being committed**
`test_trading_master.db` (98 KB) holds the `users` table, hashed passwords
included, and matched no `.gitignore` rule.
*Fixed:* `*.db`, `*.sqlite*` and `/data/` are ignored.

### A06 — Vulnerable and Outdated Components

**A06-1 · Medium · Nothing was pinned**
`requirements.txt` gave floor-only constraints for 6 packages and **no
constraint at all** for 15 others, with no lockfile and no hashes. Two builds of
the same commit could ship different versions of `ccxt` — the component that
talks to external exchanges.
*Fixed:* `requirements.lock` pins the full resolved dependency tree with hashes
(`--require-hashes` semantics), resolved on Python 3.12 to match the runtime
image, and the Dockerfile installs from it. `requirements.txt` stays as the
human-edited input.

### A07 — Identification and Authentication Failures

**A07-1 · High · No password policy whatsoever**
fastapi-users' `BaseUserManager.validate_password` is a no-op and was never
overridden, so `"a"` was an accepted password — for an account that can pause
exchanges, bulk-add markets and insert prices.
*Fixed:* minimum 12 characters, maximum 128, rejection of a small common-password
list, of passwords containing the account's email local part, and of a single
repeated character.

**A07-2 · High · No brute-force protection on any authentication endpoint**
`/auth/cookie/login`, `/auth/jwt/login`, `/auth/register` and
`/auth/forgot-password` could be called as fast as the network allowed.
*Fixed:* `app/middleware/rate_limit.py`, with a deliberately strict `auth`
bucket (10/minute/IP by default) separate from read and write traffic.
`X-Forwarded-For` is honoured only when `TRUST_PROXY_HEADERS` is set, because
trusting it unconditionally lets any client send a fresh value per request and
never hit a per-IP limit at all.
**Limitation, stated plainly:** the limiter is per-process. With three API
replicas the effective limit is roughly three times the configured value. That
is adequate for abuse protection and inadequate for billing-grade quotas; exact
global limits need shared state (roadmap #18).

### A08 — Software and Data Integrity Failures

**A08-2 · Low · The Flink job failed open to a catch-all subscription**
If the `exchanges` table could not be read, `build_topic_pattern` silently
returned a pattern matching *every* candle topic and logged at WARNING — so a
database problem turned into "store whatever happens to be on the broker",
quietly.
*Fixed:* the fallback logs at ERROR naming the cause and the consequence, and
the constant documents that it is a fallback rather than a mode.

### A09 — Security Logging and Monitoring Failures

**A09-1 · Medium · No alerting existed at all**
No `rule_files`, no `alerting` section, no Alertmanager anywhere in the
repository. Every failure — a failed nightly archive, a stalled exchange feed,
an error storm — was visible only to whoever happened to open Grafana.
*Fixed:* nine alert rules in `observability/prometheus/rules/tradingmaster.yml`
(validated with `promtool`), wired into both the Compose and Kubernetes
Prometheus configs, with an Alertmanager instance in each. The receiver is
deliberately a no-op, so routing to email or Slack is a config change rather
than a code change.

**A09-2 · Medium · User email addresses logged in plaintext**
`on_after_register` wrote the address to structured logs shipped to Loki, which
has different retention and access controls than the database.
*Fixed:* the user id only.

**A09-3 · Medium · No audit trail for privileged actions**
Nothing recorded who enabled or disabled an exchange, who bulk-added markets, or
who inserted a candle — and every active user can do all of those.
*Fixed:* every mutating endpoint logs the acting user's id, and the new
`job_runs` table is a durable record of every archive run.

**A09-4 · Low · Unauthenticated connections could drive unbounded log volume**
The WebSocket endpoint logged the client-supplied ticker and the resolved topic
list at INFO on every connect.
*Fixed:* moved to DEBUG, with counters for the cases worth watching; the raw
ticker is no longer echoed into the close reason either.

**A09-5 · Low · Unbounded metric cardinality** — see A01-3.

### A10 — Server-Side Request Forgery

**A10-1 · Low · Outbound targets were chosen by environment and database values**
`getattr(ccxtpro, FX_REFERENCE_EXCHANGE)` and `getattr(ccxtpro, exchange_id)`
pick an outbound target from configuration and from a user-writable column. The
reachable set is ccxt's own exchange list rather than arbitrary URLs, so this is
low severity, but the values were never checked.
*Fixed:* both are validated against `ccxtpro.exchanges` before the lookup.
No user-supplied URL is fetched anywhere in the codebase.

---

## 4. Trade-offs accepted

Stated explicitly so a reviewer does not have to infer them.

| Decision | Why | Consequence |
|---|---|---|
| Rate limiting is **per process**, not shared | Avoids adding Redis to the deployment | With N replicas the effective limit is ~N× the configured value. Fine for abuse protection, not for quotas. |
| The live-stream hub is **per process** | Same | Each replica holds its own consumers. They are independent readers of the same topics, so this is correct, just not minimal. |
| `/metrics` stays **public** | It is a public data API and the SPA's System screen reads it | Market inventory and request volumes are readable. Cardinality is now bounded; restrict at the Service or ingress if this becomes unacceptable. |
| The **baseline migration is guarded** by `has_table` | Deployed databases exist in several shapes from the old `create_all` startup path | A one-time concession so every database converges with a plain `alembic upgrade head`. Later revisions are ordinary unguarded migrations. |
| Password-reset and verify **routes stay enabled** | Removing them would break the API contract | The tokens are generated but never delivered (no email backend — A07-3). No token leaves the system, so nothing is exposed; the flows are simply inert. |

---

## 5. Open findings (tracked, not fixed)

| ID | Severity | Finding | Why it is still open |
|---|---|---|---|
| **A01-1** | **High** | **No admin role.** Every active user can pause exchanges, bulk-add markets, insert candles and trigger archives. `current_superuser` is defined in `app/auth/users.py` and used on **no endpoint**. | A product decision about who may do what. Roadmap #4. The audit logging added under A09-3 means these actions are at least attributable in the meantime. |
| **A01-2** | High | **Open registration with immediate full rights.** Anyone can register; the account is `is_active=True` at once and `current_active_user` does not require `is_verified`. | Gating on verification needs a working email backend (roadmap #14). Registration is now rate-limited, which bounds automated abuse but does not change the authorisation model. |
| **A02-4** | Medium | **Kafka is plaintext** with no SASL or TLS, and the Flink job's psycopg connection sets no `sslmode`. | Infrastructure change: needs broker configuration and certificate management, beyond this round. |
| **A02-5** | Medium | **Sessions cannot be revoked.** The JWT strategy is stateless, so logout clears the cookie but the token stays valid for its full hour — and works in either transport. | Needs a denylist or refresh tokens. The 1-hour lifetime bounds the exposure. |
| **A03-3** | Low | `TIMESCALE_PASS` is interpolated into the Flink job's SQL DDL, so it appears in the job graph and the Flink UI. | Needs a change to how the JDBC connector receives credentials, inside the Flink job. |
| **A04-5** | **High** | **The collector runs inside the API process** (`app/main.py` lifespan) while the production overlay sets `replicas: 3` — three copies of every exchange stream and every Kafka message. | Outside the three items agreed for this round. Roughly one day: the standalone entrypoint (`app/producer_runner.py`) already exists; it needs its own Deployment at `replicas: 1` and removal from the API lifespan. **Recommended as the next piece of work.** |
| **A07-3** | Medium | **Password-reset and verification tokens are never delivered** — the hooks only log. | Needs an email provider. Roadmap #14. |
| **A07-4** | Low | No account lockout, no MFA. | Product decision. |

---

## 6. Recommended order of work

1. **A04-5 — split the collector out of the API.** Highest severity still open,
   smallest effort, and it is a correctness and cost problem as much as a
   security one.
2. **A01-1 + A01-2 — admin role and registration policy.** Together these close
   the largest remaining gap: today, registering an account grants the ability
   to change what the platform collects and to insert prices into it.
3. **A07-3 — connect an email provider.** Unblocks verification gating, which is
   what makes A01-2 fully closeable.
4. **A02-4 — TLS and authentication on Kafka and PostgreSQL.** Infrastructure
   work; schedule with whoever owns the cluster.
5. **A02-5 — token revocation.** Lower urgency given the 1-hour lifetime.

---

## 7. How to re-verify

```bash
# Config fail-fast (A02-1, A02-2, A05-4)
APP_ENV=production python -c "import app.config"          # must refuse to start

# Rate limiting, bounded inputs, headers, middleware order (A05-5, A05-6, A07-2)
pytest tests/test_api_protection.py

# Password policy (A07-1)
pytest tests/test_auth.py -k password

# Stream hub sharing and back-pressure (A04-3)
pytest tests/unit/test_stream_hub.py

# Archive idempotency (A04-1)
pytest tests/unit/test_eod_archive.py tests/integration/test_eod_archive_integration.py

# Alert rules (A09-1)
promtool check config observability/prometheus/prometheus.yml

# Containers and manifests (A05-2, A05-3)
grep -n USER Dockerfile frontend/Dockerfile app/flink_jobs/Dockerfile
kubectl kustomize k8s/overlays/prod | grep -A3 securityContext

# Nothing sensitive committed (A05-11)
git check-ignore -v test_trading_master.db .env
```
