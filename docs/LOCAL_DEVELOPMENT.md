# Running TradingMaster locally

A working local setup, start to finish. Every command here was run on this
machine and the outputs are real.

**The one thing that changed recently:** the schema is now owned by Alembic. The
API *verifies* the database is at the migrations' head and **refuses to start**
otherwise — it no longer creates tables for you. So `alembic upgrade head` is a
required step, not an optional one.

---

## 0. Two ways to run it

**A — Everything in Docker.** One command, nothing installed on your machine but
Docker. Use this to see the whole system working, to demo it, or to test against
something production-shaped.

```bash
cp .env.example .env
./dev up
```

`./dev` is the entry point — a plain shell script, nothing to install. Run
`./dev help` for the full list. Use it rather than `docker compose` directly;
section 3.1 explains why.

That's it. Compose builds the image, starts PostgreSQL and Kafka, **applies the
database migrations**, starts the API (which also runs the exchange collector),
then the Flink job, the UI and the full observability stack — in that order,
each waiting for the previous one to be genuinely ready.

**B — Infrastructure in Docker, app on the host.** What you want while actually
writing code: hot reload, breakpoints, fast test runs.

```bash
./dev infra                                      # Postgres + Kafka + migrations
env/bin/python -m uvicorn app.main:app --reload
```

> **Run one or the other, never both.** Two API instances open duplicate
> exchange streams and publish every candle twice. If the stack is up, stop the
> `api` container before starting a host one: `docker compose stop api`.

Sections 1–2 are setup common to both. Section 3 is mode A, sections 4–9 are
mode B and the details behind both.

---

## 1. Prerequisites

```bash
python3 --version   # 3.12 (this project's venvs are 3.12.14)
node -v             # v22
docker --version
java -version       # 17 — only for the Flink job
```

---

## 2. One-time setup

### 2.1 Python environment

The repo already has `env/` (the API) and `env_flink/` (the Flink job). If you're
starting fresh:

```bash
python3 -m venv env
env/bin/pip install -r requirements.lock      # exact, hash-verified
env/bin/pip install -r requirements-test.txt
```

> `requirements.lock` is what the Docker image installs — it pins the full
> dependency tree with hashes. `requirements.txt` is the human-edited input;
> installing from it directly gives you a loose resolve, which is fine for
> poking around but won't match CI.

### 2.2 Node

```bash
cd frontend && npm install
```

### 2.3 Configuration

```bash
cp .env.example .env
```

`.env.example` documents every setting. The defaults are fine for local work —
you do **not** need exchange API keys, because the candle streams are public.

**⚠️ Port 5432 is already taken on this machine.** Something other than Docker
owns it (it answers as PostgreSQL but rejects the project's credentials). Your
`.env` is therefore already set to publish the project's Postgres on **5433**:

```dotenv
POSTGRES_HOST_PORT=5433
TIMESCALE_URL=postgresql+asyncpg://user:mysecretpassword@localhost:5433/tradingmaster
```

Those two must always agree. If you free up 5432 later, set both back to 5432.

To check what's holding it:

```bash
ss -ltnp | grep 5432        # add sudo to see the owning process
```

---

## 3. Mode A — the whole stack in Docker

```bash
docker compose up -d --build
```

The first build takes a few minutes: it compiles the UI bundle and installs the
Python dependencies from `requirements.lock` with hash verification.

The first build takes a few minutes. Subsequent ones are fast — Docker reuses
the layers that didn't change.

### 3.1 Why `./dev` and not `docker compose` directly

`docker compose up -d` starts whatever image already carries the tag the compose
file names. **It does not look at your source.** So you can edit code, bring the
stack up, and silently run last week's build — with nothing in the output saying
so. That happened twice while writing this document:

| Symptom | Actual cause |
|---|---|
| Flink died on `UnknownTopicOrPartitionException` for `binance.BTCUSDT.candles` | image predated the unified-feed rename (`BTCUSD`), so it subscribed to topics nobody publishes to any more |
| The UI served fine but with **no security headers** | image predated the `nginx.conf` change — nothing failed, the hardening was just absent |

Both looked like application bugs. Neither was. `--build` fixes it, but only if
you remember every time, and you will not.

So the images are **content-addressed**. `scripts/image-tag.sh` hashes every file
that goes into them and `./dev` passes that hash as the image tag:

```yaml
image: tradingmaster-api:${TM_IMAGE_TAG:-dev}
```

Change one Python file and the tag changes. No image exists under the new tag, so
Compose has to build it — Docker reuses the unchanged layers, so it's quick.
**Staleness stops being a thing you remember and becomes a thing that cannot
happen.**

```bash
./dev stale        # is any image behind the working tree?
```

```
working tree tag: d7c4d3fe8c4a
  tradingmaster-api          up to date
  tradingmaster-flink        up to date
  tradingmaster-frontend     up to date
```

Because every source change makes a new tag, old images pile up. Clear them out:

```bash
./dev clean-images     # removes any project image not matching the current source
```

> Plain `docker compose` still works — it just falls back to the tag `dev` and
> gives you none of this protection. Fine for `docker compose logs`, not for
> starting things.

### What comes up, and in what order

Compose does not just start everything at once — each service waits for the one
it actually needs:

```
postgres (healthy)
   └── migrate  ......... alembic upgrade head, runs to completion, exits
          └── api  ...... REST + WebSocket + UI + exchange collector
                 ├── flink ....... persists candles to PostgreSQL
                 └── frontend .... nginx (only if you want the standalone UI)
kafka (healthy) ────────┘
```

`migrate` is deliberately **not** optional. If it didn't run, the API would
refuse to start (it verifies the schema is at head) and the failure would look
like a bug rather than a missing step.

`flink` waits for the API specifically because the API seeds the
`exchanges`/`symbols` tables on startup. Starting first, Flink would read an
empty table and fall back to subscribing to every topic on the broker.

### Watch it come up

```bash
docker compose ps
docker compose logs -f api
```

All services healthy looks like:

```
NAME                      STATUS
tradingmaster-postgres    Up (healthy)
tradingmaster-kafka       Up (healthy)
tradingmaster-migrate     Exited (0)          <- correct: it is a one-shot job
tradingmaster-api         Up (healthy)
tradingmaster-flink       Up
tradingmaster-frontend    Up
...
```

A `migrate` container sitting at `Exited (0)` is success, not a failure.

### Check it

```bash
curl http://localhost:8000/health                       # {"status":"ok"}
curl -s http://localhost:8000/api/v1/market/markets     # "Found 20 market(s)"
open http://localhost:8000                              # the UI
```

Give it a couple of minutes, then confirm the whole pipeline is really working —
exchanges → Kafka → Flink → PostgreSQL:

```bash
docker exec tradingmaster-postgres psql -U user -d tradingmaster \
  -c "select exchange, interval, count(*) from candles group by 1,2 order by 3 desc limit 5"
```

Real output after ~2 minutes on a laptop:

```
 exchange | interval | count
----------+----------+-------
 kraken   | 1d       |   783
 kraken   | 1m       |   783
 coinbase | 30s      |   758
```

If `candles` stays empty but the live stream works, Flink is the problem — see
troubleshooting.

### Useful subsets

You rarely need all fifteen containers.

```bash
# Just the app, no observability
docker compose up -d --build api flink frontend

# Just infrastructure, for host development (mode B)
docker compose up -d postgres kafka migrate

# Add the observability stack when you want it
docker compose up -d prometheus grafana alertmanager

# One-shot tools
docker compose run --rm eod-archive 2026-10-03 --dry-run
docker compose run --rm migrate                       # re-apply migrations
```

### Ports

All host ports are overridable in `.env`, because something else on your
machine may already own them:

| Setting | Default | Service |
|---|---|---|
| `API_HOST_PORT` | 8000 | API + UI |
| `POSTGRES_HOST_PORT` | 5432 | PostgreSQL |
| `KAFKA_HOST_PORT` | 9092 | Kafka |

```bash
# e.g. if something already has 5432
POSTGRES_HOST_PORT=5433 docker compose up -d postgres
```

> If you change `POSTGRES_HOST_PORT` or `KAFKA_HOST_PORT`, update
> `TIMESCALE_URL` / `KAFKA_BOOTSTRAP_SERVERS` in `.env` to match — those are
> what *host-run* commands (Alembic, pytest, uvicorn) use. The containers ignore
> them: Compose overrides them with the in-network addresses `postgres:5432` and
> `kafka:29092`, because `localhost` inside a container means that container.

---

## 3b. Mode B — infrastructure in Docker, app on the host

```bash
docker compose up -d postgres kafka migrate
```

`migrate` applies the schema and exits. Then run the app from your venv — the
rest of this document (sections 4 onward) covers that path.

---

## 4. Apply the database schema

**Required.** The API will not start without it.

```bash
env/bin/python -m alembic upgrade head
```

First run:

```
Running upgrade  -> 0001_baseline, baseline schema
Running upgrade 0001_baseline -> 0002_legacy_alignment, ...
Running upgrade 0002_legacy_alignment -> 0003_archive_safety, ...
```

Check it:

```bash
env/bin/python -m alembic current     # 0003_archive_safety (head)
env/bin/python -m alembic check       # "No new upgrade operations detected."
```

`alembic upgrade head` is idempotent — re-run it any time. It's also what you run
after pulling changes that touch the models.

---

## 5. Run the API

```bash
env/bin/python -m uvicorn app.main:app --reload
```

The API starts the exchange collector automatically, so you get live data
immediately. Within a minute or so you should see candles flowing.

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -s http://localhost:8000/api/v1/market/markets | head -c 200
# {"status":"success","message":"Found 20 market(s)", ...
```

Interactive docs: <http://localhost:8000/docs>

### Watch the live stream

```bash
env/bin/python - <<'PY'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://localhost:8000/api/v1/market/ws/live/BTCUSD") as ws:
        for _ in range(3):
            p = json.loads(await ws.recv())
            if p.get("type") == "heartbeat":   # sent on a quiet market
                continue
            print(f"{p['exchange']:9} {p['ticker']} {p['interval']:4} "
                  f"close={p['close_price']}  src={p['source_ticker']} fx={p['fx_rate']}")
asyncio.run(main())
PY
```

Real output from this machine:

```
binance   BTC/USD 1m   close=84749.11156000  src=BTC/USDT fx=0.99973000
binance   BTC/USD 1m   close=84743.11318000  src=BTC/USDT fx=0.99973000
```

That's the unified feed working: Binance quotes `BTC/USDT`, and it arrives as
`BTC/USD` converted at the live Kraken rate.

---

## 6. Run the UI

Two ways. Pick one.

**Dev server (hot reload)** — what you want while working on the UI:

```bash
cd frontend && npm run dev     # http://localhost:5173
```

It proxies `/api` and the WebSocket to `:8000`, so everything is same-origin and
cookie auth works.

**Served by FastAPI** — closer to production, no second process:

```bash
cd frontend && npm run build   # writes frontend/dist
```

FastAPI picks `frontend/dist` up automatically and serves it at
<http://localhost:8000/>.

---

## 7. Create an account

Reading is public; changing anything needs a login.

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"tester@example.com","password":"correct-horse-battery-staple"}'
```

**The password policy will reject weak passwords** — minimum 12 characters, and
it may not contain your email's local part. This trips people up:

```bash
# email dev@example.com + password "local-dev-password-123" ->
# {"detail":{"code":"REGISTER_INVALID_PASSWORD",
#            "reason":"Password must not contain your email address."}}
```

Then log in and use the token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/jwt/login \
  -d 'username=tester@example.com&password=correct-horse-battery-staple' \
  | env/bin/python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -X POST http://localhost:8000/api/v1/exchanges \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"binance","method":"multi"}'
```

In the browser the UI uses an http-only cookie instead, so no token is ever
exposed to page JavaScript.

---

## 8. Full pipeline — persist candles with Flink

Up to now candles reach Kafka and the live stream, but **nothing is stored**.
The Flink job is what writes them to Postgres, which is what makes
`/api/v1/market/candles` and the history endpoints return anything.

```bash
# These must be exported in the job's own shell — activating env_flink does NOT
# read .env. Note the 5433 port.
export TIMESCALE_JDBC_URL="jdbc:postgresql://localhost:5433/tradingmaster"
export TIMESCALE_USER=user
export TIMESCALE_PASS=mysecretpassword
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092

env_flink/bin/python app/flink_jobs/candle_builder.py
```

Run it as a **script**, not `python -m app.flink_jobs...`.

If the JARs are missing: `scripts/download_flink_jars.sh`.

After about a minute:

```bash
docker exec tradingmaster-postgres psql -U user -d tradingmaster \
  -c "select exchange, ticker, interval, count(*) from candles group by 1,2,3 order by 4 desc limit 5"
```

Real output after 75 seconds:

```
 exchange |  ticker  | interval | count
----------+----------+----------+-------
 coinbase | ATOM/USD | 30s      |   107
 coinbase | ATOM/USD | 1m       |    72
 coinbase | BCH/USD  | 30s      |    69
```

And the REST API now returns them:

```bash
curl -s "http://localhost:8000/api/v1/market/candles/BTC%2FUSD?interval=30s&limit=2"
```

---

## 9. End-of-day archive

Copies a day's candles into history, writes Parquet, prunes the hot table.

```bash
env/bin/python -m app.eod_runner 2026-10-03               # archive a day
env/bin/python -m app.eod_runner 2026-10-03 --dry-run     # report only
env/bin/python -m app.eod_runner 2026-10-03 --replace     # re-archive after fixing data
```

**Re-running is safe** — that's the point of the recent change. Real output:

```
run 1:  1252 archived, 0 already present, 46 file(s)
run 2:  0 archived, 1252 already present, 46 file(s)
```

Still 1252 rows, 1252 distinct keys. Before, run 2 would have appended a second
copy of the day.

Exit codes: `0` ok · `1` failed · `2` another run holds the lock · `3`
`--replace` refused (the day's source candles are already gone, so it would
delete an archive it can't rebuild).

Where things land:

```bash
find data -name '*.parquet' | head
# data/coinbase/LINK-USD/2026-10-03.parquet

curl -s http://localhost:8000/api/v1/history/archive/runs | head -c 200
```

That last endpoint is how you see whether the scheduled job is healthy — the
job runs in its own process, so nothing scrapes its metrics directly.

---

## 10. Tests

No Docker needed — API tests use temporary SQLite and mock Kafka.

```bash
env/bin/python -m pytest                  # 424 passed, 5 skipped
env/bin/python -m pytest tests/unit       # fast, fully mocked
env/bin/python -m pytest tests/test_market.py -k candles

cd frontend && npm run test:run           # 96 passed
```

The 5 skipped are the migration tests, which need a real PostgreSQL. To run them:

```bash
docker run -d --name tm-test-pg -e POSTGRES_USER=user -e POSTGRES_PASSWORD=testpw \
  -e POSTGRES_DB=tradingmaster -p 55432:5432 postgres:16

TEST_POSTGRES_URL=postgresql://user:testpw@localhost:55432/tradingmaster \
  env/bin/python -m pytest tests/integration/test_migrations.py

docker rm -f tm-test-pg
```

---

## 11. Observability (optional)

```bash
docker compose up -d prometheus grafana alertmanager
```

| What | Where | Notes |
|---|---|---|
| Prometheus | <http://localhost:9090> | check **Status → Rules** for the 9 alerts |
| Alertmanager | <http://localhost:9093> | receiver is a deliberate no-op |
| Grafana | <http://localhost:3000> | `admin` / `admin` |

The Grafana dashboard defaults to a 7-day window so the once-daily archive is
actually visible.

Tracing is **off** in your `.env` (`OTEL_ENABLED=false`). Leave it off unless you
start Jaeger, or every request logs an exporter connection error:

```bash
docker compose up -d jaeger    # then set OTEL_ENABLED=true and restart the API
```

Validate the alert rules without running anything:

```bash
docker run --rm -v "$PWD/observability/prometheus:/etc/prometheus:ro" \
  --entrypoint promtool prom/prometheus:v2.55.1 \
  check config /etc/prometheus/prometheus.yml
```

---

## 12. Stopping and resetting

```bash
docker compose stop                 # stop everything, keep data
docker compose down                 # remove containers, keep volumes
docker compose down -v              # ALSO wipe the database and archives — full reset
docker compose restart api          # pick up a changed .env
```

After `down -v`, the next `docker compose up -d` re-runs `migrate` and reseeds
from scratch.

Host-run processes (mode B) are separate from Compose and need stopping
themselves:

```bash
pkill -f "uvicorn app.main:app"
pkill -f candle_builder.py
pkill -f "node.*vite"
```

Two named volumes hold state:

| Volume | Holds | Survives |
|---|---|---|
| `postgres_data` | the database | `down`, not `down -v` |
| `archive_data` | EOD Parquet files written by the api/eod-archive containers | `down`, not `down -v` |

The database used to live in the container layer, which meant recreating the
container silently kept a database initialised with *different credentials* —
`POSTGRES_PASSWORD` only applies on first init. The named volume makes resets
explicit.

To copy archives out of the container:

```bash
docker compose cp api:/app/data ./data-from-container
```

---

## 13. Troubleshooting

These are the errors actually hit while setting this up.

### Flink exits with `UnknownTopicOrPartitionException` on `binance.BTCUSDT.candles`

Note the ticker: `BTCUSDT`, not `BTCUSD` — a pre-unified-feed topic name. The
container is running an image built before that change.

This is what content-addressed tags prevent. If you see it, you started the
stack with raw `docker compose` rather than `./dev`:

```bash
./dev stale          # confirms which images are behind
./dev up             # rebuilds them
```

Stale *topics* can also linger on the Kafka broker from an older run. They are
harmless — nothing publishes to them — but `./dev reset` clears everything.

### The UI works but security headers are missing

Same cause, same fix: a frontend image built before `nginx.conf` changed.
Nothing fails, the hardening is just absent — which is why `./dev stale` exists.

```bash
curl -sI http://localhost:5174/ | grep -i content-security-policy
```

### `address already in use` on `docker compose up`

Something on your machine owns the port. Override it in `.env` —
`API_HOST_PORT`, `POSTGRES_HOST_PORT`, `KAFKA_HOST_PORT` — rather than fighting
over the default. To find the owner:

```bash
ss -ltnp | grep 8000        # add sudo to see the process
```

A common case is a host-run `uvicorn` from mode B still holding `:8000` — and
note that **`pkill -f "uvicorn app.main:app"` will not kill it.** Under
`--reload` the serving process is a `multiprocessing` child whose command line
contains neither "uvicorn" nor "app.main", so it survives the pattern kill,
gets reparented to systemd, and keeps the socket. `ps aux | grep uvicorn` shows
nothing, which makes the port look haunted.

Identify by port, not by name:

```bash
ss -ltnp | grep :8000       # sudo if the PID column is blank
#   LISTEN 127.0.0.1:8000   users:(("python",pid=7088,fd=3))
kill 7088
```

### `tradingmaster-migrate` shows `Exited (0)` — is that broken?

No, that's success. It's a one-shot job: it applies the migrations and exits.
`Exited (1)` would be a failure — check `docker compose logs migrate`.

### The api container starts, then candles appear twice

You have two collectors running — most likely the `api` container *and* a
host-run `uvicorn`. Stop one:

```bash
docker compose stop api        # if you want the host one
```

### `docker compose up` hangs on "waiting for api to be healthy"

The API's healthcheck has a 20s grace period and then polls `/health`. If it
never goes healthy:

```bash
docker compose logs api
```

The usual cause is the database — if `migrate` failed, the API refuses to start
by design.

### Container can't reach Postgres/Kafka though the host can

Inside a container, `localhost` means *that container*. Services must use the
network names: `postgres:5432` and `kafka:29092` (the INTERNAL listener, not
9092). `docker-compose.yml` sets these for you by overriding the `.env` values —
if you added a service by hand, that's the thing to check.

### `asyncpg.exceptions.InvalidPasswordError` on `alembic upgrade head`

Your `TIMESCALE_URL` is pointing at the *other* PostgreSQL on 5432. Check that
`POSTGRES_HOST_PORT` and the port inside `TIMESCALE_URL` agree, and that the
container really published it:

```bash
docker port tradingmaster-postgres
```

### The API and Alembic disagree about which database they mean

There used to be **two** `.env` files — the repo root one and `app/.env` — and
which one won depended on the entry point, because `load_dotenv()` searches
upward from the *calling file*. `uvicorn` picked up the root one; `alembic`
picked up `app/.env`.

Fixed: `app/config.py` now loads the repo-root `.env` by explicit path. The
leftover file was moved to `app/.env.unused-backup`; delete it when you're happy.

If you ever see this class of confusion again:

```bash
env/bin/python -c "import app.config as c; print(c.TIMESCALE_URL)"
```

### `The database has no Alembic version stamp — it has never been migrated.`

Working as designed. Run `alembic upgrade head`. The API refuses to start against
an unknown schema rather than failing later in a confusing way.

### `REGISTER_INVALID_PASSWORD`

Minimum 12 characters, and it must not contain your email's local part. See §7.

### `429 Too Many Requests`

The rate limiter. Defaults are generous in your `.env`, but the auth bucket is
deliberately strict. For a load test, raise it or set `RATE_LIMIT_ENABLED=false`.

### WebSocket handshake returns `HTTP 403`

You exceeded `RATE_LIMIT_WS_CONNECT_PER_MINUTE` (opening many sockets in a loop).
Raise it in `.env`. Close codes in normal operation: **1008** unknown market
(permanent — the UI won't retry), **1013** at capacity or rate-limited
(temporary — it will).

### `/api/v1/market/candles/...` returns 404 but the live stream works

Expected without Flink. The live stream reads Kafka directly; the REST endpoint
reads the database, and only Flink writes there. See §8.

### Flink: "Derby factory" / connector errors

Missing JARs — the JDBC connector is modular in Flink 2.x and needs the Postgres
dialect JAR specifically. Run `scripts/download_flink_jars.sh`.

---

## 14. Quick reference

### Everything in Docker

```bash
cp .env.example .env
./dev up              # builds whatever changed, then starts the lot
./dev ps
./dev logs api
./dev down            # stop;  ./dev reset also wipes the data
```

### Host development

```bash
./dev infra           # Postgres + Kafka + migrations only
env/bin/python -m uvicorn app.main:app --reload
cd frontend && npm run dev

# Flink, in its own shell — exports required, env_flink does NOT read .env
export TIMESCALE_JDBC_URL="jdbc:postgresql://localhost:5432/tradingmaster" \
       TIMESCALE_USER=user TIMESCALE_PASS=mysecretpassword \
       KAFKA_BOOTSTRAP_SERVERS=localhost:9092
env_flink/bin/python app/flink_jobs/candle_builder.py
```

### Checks

```bash
./dev verify          # typecheck + both suites (what CI would run)
./dev typecheck       # tsc --noEmit — the tests do NOT typecheck
./dev test
env/bin/python -m alembic check        # models vs migrations
```

### Images

```bash
./dev stale           # is any image behind the working tree?
./dev clean-images    # drop images that no longer match the source
./dev rebuild         # ignore the layer cache
```

### One-shot tools

```bash
./dev migrate                          # re-apply migrations
./dev archive 2026-10-03 --dry-run
./dev archive 2026-10-03
./dev psql                             # psql shell
```

### Where things listen

| URL | What |
|---|---|
| <http://localhost:8000> | API + UI (`API_HOST_PORT`) |
| <http://localhost:8000/docs> | Swagger |
| <http://localhost:8000/metrics> | Prometheus metrics |
| <http://localhost:5173> | UI dev server (mode B only) |
| <http://localhost:5174> | UI standalone nginx container |
| `localhost:5432` | PostgreSQL (`POSTGRES_HOST_PORT`) |
| `localhost:9092` | Kafka (`KAFKA_HOST_PORT`) |
| <http://localhost:9090> | Prometheus — **Status → Rules** for the 9 alerts |
| <http://localhost:9093> | Alertmanager |
| <http://localhost:3000> | Grafana (`admin`/`admin`) |
| <http://localhost:16686> | Jaeger (needs `OTEL_ENABLED=true`) |
| <http://localhost:5050> | pgAdmin |

### Inside a container, addresses differ

| From the host | From inside Compose |
|---|---|
| `localhost:5432` | `postgres:5432` |
| `localhost:9092` | `kafka:29092` (INTERNAL listener) |
| `localhost:8000` | `api:8000` |

`docker-compose.yml` handles this for you by overriding the `.env` values on
each service — it only matters if you add a service yourself.
