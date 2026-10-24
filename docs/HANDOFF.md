# Handoff — TradingMaster (updated 2026-10-22)

Written so you can pick this up cold.

- **Start with Part C below.** It covers the latest conversation and the
  implemented development trading MVP. The changes are **not committed**.
- **Parts A and B are historical handoffs.** Their repository-state snapshots,
  test counts and suggested next steps are superseded by Part C. In particular,
  the names/i18n/SEO work described as uncommitted in A2 has since been committed.
- **Part A** covers local currencies, stocks, instrument names, seven languages
  and SEO.
- **Part B** (§0–§7) is the earlier September round: migrations, archive safety,
  the security audit and local dev. Architectural limitations still apply unless
  a later section explicitly records a fix.

---

# Part C — 2026-10-22: development trading MVP

## C1. Conversation and agreed product decisions

The user first requested a contributor guide, with an explicit instruction to
leave an existing `AGENTS.md` alone. It already existed and **was not modified**.
Its repository instructions continue to apply.

Business then requested buying, a configurable development Guest and funds,
**My Trades** with spread-aware profit/loss and selling, payment-method TODOs,
development credits/top-ups, and tests. The feature was planned with the user,
then the user explicitly requested implementation. These choices were confirmed:

- **Simulated trades only**, limited to development. No real exchange orders,
  custody, card charges, PayPal integration or bank-transfer processing.
- **Guest login credentials**, using the existing login flow, rather than
  anonymous browser wallets. Guest is an optional seeded account; registered
  users can also trade, with separate wallets.
- **An app configuration setting controls starting credits for every user.**
  It is applied once to each new wallet, not reset on restart or configuration
  changes. Default: 10,000 credits; **1 credit = 1 USD**.
- **Real provider bid/ask**, rather than a configurable artificial spread.
  Both crypto and stocks are included. Yahoo stock delays and incomplete
  coverage were accepted; unavailable or unreliable quotes disable trading.
- Users enter a **credit budget**. Fractional units/shares are supported; each
  purchase is its own trade, and selling closes that trade **in full**.
- Development supports **Add demo credits**. Card, PayPal and bank transfer
  remain disabled **Coming soon / TODO** placeholders.

Implementation is complete for that scope. Remaining work is migration/runtime
verification and review, as listed in C5; there is no pending product question.

## C2. Implementation map and behavior

| Area | Implementation |
|---|---|
| Configuration | `app/config.py`: opt-in development flags, initial funds, Guest credentials, quote age limits and startup validation; `.env.example` documents them. |
| Persistence | `app/models/trading.py`: wallet, executable quote, trade and credit ledger. `users.is_dev_guest` identifies provisioned Guests without exposing that marker in public user schemas. |
| Migration | `migrations/versions/2026_10_22_1200-0006_development_trading.py`, after `0005_instruments`; creates the trading tables and Guest marker, with a downgrade. |
| Guest | `app/trading/guest.py`, called during API startup. Uses existing password validation/hashing, rejects unrelated email collisions case-insensitively, and preserves existing Guest passwords. |
| Quotes | `app/trading/quotes.py`: on-demand public CCXT order books and Yahoo bid/ask; provider timeouts, bounded concurrency, two-second successful-snapshot cache and USD conversion. Independent of Kafka/Flink candles. |
| Accounting/execution | `app/trading/service.py`: persistent 15-second previews, per-wallet SQL serialization, idempotency, purchases, full sales, ledger entries and valuations. |
| API | `app/routers/trading.py`, inputs in `app/schemas/trading.py`, mounted in `app/main.py`. |
| UI | `PurchasePanel.tsx`, `TradeConfirmation.tsx`, `TradesPage.tsx`, typed client/hooks in `frontend/src/lib/{api,trading}.ts`; `/trades` navigation and localized routes. |
| Localization/SEO | Trading UI translations in all seven existing languages; server/client SEO text updated together. `/trades` is private, `noindex`, and absent from the sitemap. |
| Documentation | README section **Development simulated trading** includes setup, API examples and limitations. |

Accounting rules to preserve:

- Use `Decimal`/`Numeric(28, 8)` and decimal strings in responses. Quantities
  round down to eight places; charge their actual rounded cost and retain the
  unused credits. Reject purchases that round to zero.
- Buy at ask; sell/value open holdings at bid. Spread is `ask - bid`; spread
  percentage uses the midpoint. Unrealized P/L is current bid value minus cost;
  realized P/L is sale proceeds minus cost. **Do not subtract spread twice.**
- The chart's display-currency picker does not change credit settlement.
- Wallet changes, trade state, quote consumption and ledger entries commit
  atomically. Duplicate or concurrent requests cannot overspend or double sell.
- Executable previews are user-owned, expire after 15 seconds or sooner when
  the source/session expires, and retain their quoted price through confirmation.
  Recheck market availability before execution; expired quotes need a new preview.
- Source symbols come from enabled DB configuration. Sales retain the original
  source market. Missing valuations are unknown, never zero.
- Stock quotes require an open regular session, source time, and usable session
  metadata. Yahoo's `regularMarketTime` is a freshness proxy, **not a separate
  bid/ask timestamp**. Crypto books without a provider timestamp retain NULL
  source time and use retrieval time for freshness.
- Source age defaults: crypto 30 seconds, stocks 1,200 seconds. Fiat FX requires
  an ECB rate no older than seven days; stablecoin conversion fetches a live FX
  order book and never substitutes the candle feed's peg fallback.
- Fees, partial sales, limit orders, shorting, order-book depth and slippage are
  deferred. Disabled source markets cannot be traded until enabled again.

## C3. API contract

All paths below are relative to `/api/v1/trading` and return the existing
`ApiResponse` envelope. `GET /capabilities` is public. Other endpoints require
an active authenticated user and enabled development trading; cookie writes
also require the existing `X-Requested-With` CSRF header.

| Method/path | Purpose/input |
|---|---|
| `GET /capabilities` | Feature availability, simulation flag and payment-method statuses. |
| `POST /wallet/initialize` | Idempotently seed this user's wallet once. |
| `GET /wallet` | Current credit balance. |
| `POST /wallet/demo-top-ups` | `{"amount":"1000"}` plus UUID `Idempotency-Key`. |
| `POST /quotes` | Buy: `{"side":"buy","exchange":"kraken","ticker":"BTC/USD","budget":"100"}`; sell: `{"side":"sell","trade_id":"<UUID>"}`. |
| `POST /trades` | `{"quote_id":"<UUID>"}` plus UUID `Idempotency-Key`. |
| `GET /trades` | `status=open|closed`, `limit` (default 10, max 50), `offset`; open results include current valuations or an unavailable reason. |
| `POST /trades/{id}/sell` | `{"quote_id":"<UUID>"}` plus UUID `Idempotency-Key`. |

Reuse an idempotency key only to retry an identical request. Changed requests
with the same key return conflict. Clients cannot supply executable prices or
payment-provider details. UI purchase retries preserve the same key.

## C4. Verification actually performed

| Check | Observed result |
|---|---|
| `env/bin/python -m pytest -q -o log_cli=false` | **618 passed, 6 skipped** at that point in implementation. |
| Final focused run: `env/bin/python -m pytest tests/test_trading.py tests/test_trading_guest.py tests/unit/test_trading_quotes.py -q -o log_cli=false` | **51 passed**, after adding the final stock/FX, wallet-initialization and case-insensitive Guest-collision coverage. This overlaps the full suite; do not add the counts together. |
| `cd frontend && npm run test:run -- --silent` | **208 passed** in 18 files, including eight new trading UI tests. |
| `cd frontend && npm run build` | Passed; Vite reports a roughly 600 kB main bundle warning. |
| `env/bin/python -m alembic upgrade 0005_instruments:head --sql` | PostgreSQL upgrade SQL generated successfully; constraints checked against model naming. |
| `git diff --check` | Passed. |

Tests cover spread loss, profitable/losing sales, rounding, insufficient funds,
ownership isolation, private reads, CSRF, development gating, quote expiry,
idempotent retries, concurrent purchases/sales, ledger rollback, Guest provisioning
and login, stock session metadata, and live-FX/no-rate behavior. UI tests cover
preview/confirmation, network retry keys, expiry, demo top-ups, unavailable
valuations, profit/loss and disabled real-payment methods.

**Verification limits:** The six PostgreSQL migration tests skipped because
`TEST_POSTGRES_URL` was not configured. Migration upgrade/downgrade/drift checks
were extended but not run against PostgreSQL in this conversation. External
quote-provider responses were mocked in tests; the new flow was not exercised
against live providers or in a real browser. No deployment or application-database
migration was performed. Existing Pydantic deprecations/AsyncMock warnings remain.

Sandboxed backend tests stalled in aiosqlite's worker/event-loop communication
before reaching test logic. They passed outside the sandbox after approval.
Do not change business logic or fixtures to work around that sandbox behavior.

## C5. Next engineer's startup and remaining checks

1. Read this section, `AGENTS.md`, and README's development-trading section.
   Inspect `git status` before editing or committing; preserve unrelated changes.
2. Apply migrations to the intended development database:

   ```bash
   source env/bin/activate
   alembic upgrade head
   ```

3. Configure the repo-root `.env` locally. These are examples, not credentials
   created or installed by this session:

   ```dotenv
   APP_ENV=development
   DEV_TRADING_ENABLED=true
   DEV_INITIAL_CREDITS=10000
   DEV_GUEST_ENABLED=true
   DEV_GUEST_EMAIL=demo@example.com
   DEV_GUEST_PASSWORD=<choose-a-password-that-passes-the-existing-policy>
   TRADING_CRYPTO_MAX_AGE_SECONDS=30
   TRADING_STOCK_MAX_AGE_SECONDS=1200
   ```

   Guest is optional. Its password must be at least 12 characters and must not
   contain the email's local part or match a disallowed common password. The
   API refuses enabled trading/Guest flags outside `APP_ENV=development`.
4. Start/rebuild with the established `./dev up` workflow, or run the API/UI
   locally as documented. Compose's API reads the repo-root `.env` through
   `env_file`; its database/Kafka host overrides still apply.
5. Manually verify Guest login, configured initial funds, purchase preview and
   confirmation, immediate spread loss in My Trades, full sale and closed history,
   demo top-ups, registered-user isolation and balance preservation after restart.
   Check both a crypto market and stocks during regular trading hours. A stock
   without usable Yahoo bid/ask should show unavailable, not a fabricated quote.
6. Configure `TEST_POSTGRES_URL` to a **disposable** PostgreSQL instance and run
   `env/bin/python -m pytest tests/integration/test_migrations.py -q`. The tests
   create/drop scratch databases; do not point them at production. Re-run the
   whole backend suite if a single final aggregate count is needed: the six
   latest focused cases were added after the recorded 618-pass full run.
7. Review the uncommitted patch and include new source, tests, migration and
   locale changes together. No new dependency was required. No commit, PR or
   push was created during implementation or this handoff.

## C6. Workspace ownership and unchanged limitations

Current HEAD when this handoff was written: `46a00fd Update CLAUDE.md`.
`022665e` already committed the preceding SEO/language/instrument work, so A2's
claim that those changes are uncommitted is historical.

At the start of trading implementation, `.gitignore` was already modified and
these files were already untracked: `.env.example`, `docs/BUSINESS_SUMMARY.md`,
`docs/HANDOFF.md`, `docs/SECURITY_AUDIT.md`, and `requirements.lock`. Preserve
that work; review it separately when preparing a commit. Trading configuration
was appended to `.env.example`; this handoff adds Part C while retaining A/B.
Other current app/frontend/test changes are the uncommitted trading feature.

The generated, tracked `frontend/tsconfig.app.tsbuildinfo` was restored to its
original contents after build verification. `AGENTS.md`, local secrets, real
balances and deployment manifests were not modified. Do not blindly run old
bulk staging commands from A2/B2 against the current mixed workspace.

Earlier architecture gaps remain: producer duplication across API replicas,
missing admin separation, open registration, non-durable Kubernetes archives,
and plain PostgreSQL rather than enabled TimescaleDB. See Part B §6 and
`docs/SECURITY_AUDIT.md`; the simulated trading feature does not resolve them.

---

# Part A — October 2026: currencies, stocks, names, languages, SEO

## A1. What was asked, and what was delivered

Two requests, delivered in two rounds.

**Round 1 — "we only support USD."** The ask was prices in local currencies,
picked by the country the app runs in, plus company stocks and more crypto.

| Delivered | How it works | Where |
|---|---|---|
| **30 display currencies** (PLN, EUR, NOK, SEK, GBP, CHF, …) | Storage, Kafka and Flink stay **USD-only**. REST, history and the WebSocket take `?currency=PLN` and convert on read, using the **ECB daily reference rate for each candle's own date**. A weekend candle uses Friday's rate. | `app/helpers/currencies.py`, `app/fiat/`, table `fiat_rates`, `GET /api/v1/currencies` |
| **Currency picked by location** | The browser checks, in order: a session choice, the user's profile, the browser's saved choice, the **time zone** (Europe/Warsaw → PLN), the browser language, and finally the server's `DEFAULT_CURRENCY`. There is a header picker, and the choice is saved to the user profile (`users.preferred_currency`). | `frontend/src/lib/currency.ts`, `currency-context.tsx` |
| **25 stocks**: 10 US, 10 Warsaw (GPW), 3 Xetra, 2 Oslo | A new non-ccxt source, `yahoo` (`method="poll"`), polls `yfinance`. Fiat-quoted stocks (`PKN.WA/PLN`) are converted to USD on the way in with the same ECB rate, so they read back as the quoted price. | `app/kafka/yahoo_source.py`, `app/helpers/sources.py` |
| **51 → 101 crypto markets** | Seeder additions. A pair an exchange doesn't list is skipped with a log line. | `app/models/seeder.py` |

**Round 2 — "tickers aren't enough, and it must be SEO-friendly."** The ask was
for BTC/USD to read as *Bitcoin, a cryptocurrency* and AAPL as *Apple*, plus a
dictionary of markets, translation by location and proper SEO.

| Delivered | How it works | Where |
|---|---|---|
| **Names and classification** for all 65 instruments | A curated catalogue, seeded **insert-only** into the new `instruments` table, so operator edits are never overwritten. `PUT /api/v1/instruments/{symbol}` names markets added later; an unnamed market falls back to its symbol. | `app/helpers/instruments.py`, `app/models/instrument.py`, `app/routers/instruments.py` |
| **Markets directory** (the "dictionary") | `/markets` shows a searchable, filterable table. Each row links to the market's own page. | `frontend/src/pages/MarketsPage.tsx` |
| **7 languages**: EN, PL, DE, FR, NO, IT, ES | i18next on the UI, with English bundled and the other languages loaded on demand. The server owns the taxonomy labels, descriptions and SEO text (`app/i18n/locales`); the UI owns its own text (`frontend/src/locales`). The language is detected like currency: saved choice, then a non-English browser language, then the time-zone country, then English. Proper nouns are never translated. | `frontend/src/lib/i18n.ts`, `app/i18n/` |
| **SEO** | Every page and language has its own URL (`/markets/bitcoin-btc`, `/pl/markets/bitcoin-btc`). The server writes into the HTML: title, description, canonical, 7 `hreflang` links plus `x-default`, Open Graph, and JSON-LD (breadcrumbs, and `tickerSymbol` such as `WSE:PKN` for stocks). Unknown pages are a **real 404 + noindex**. Also new: `robots.txt` and `sitemap.xml` (476 URLs). | `app/seo.py`, `frontend/src/components/Seo.tsx` |

**Tests now: 573 backend + 200 frontend, all passing** (up from 424 + 96).
Migrations, ECB download and storage, PLN conversion and the server-rendered
head were also verified **against a real PostgreSQL**, and `nginx -t` passes on
the new config. The pages were *not* looked at in a real browser — only jsdom
and raw HTML. Do that first (§A3).

### Bugs caught along the way

- **The ECB fetcher died with Kafka.** Its first home was inside
  `run_producer`, which exits when Kafka is unreachable, and its `finally`
  cancelled the fetcher with it. No rates meant no currency except USD. It now
  runs as its own task in the API lifespan and in `producer_runner`. A
  live run caught this; the unit tests didn't.
- **BGN was dropped.** Bulgaria joined the euro on 2026-01-01 and the ECB no
  longer publishes it. Offering it would only ever have produced 503s.
- **Yahoo prices carry float32 noise** (`331.7900085449219`). They are rounded
  to 4 dp, which is the finest stock tick.
- **Yahoo daily bars are keyed at local midnight**, which is 22:00 UTC the day
  before. They are re-keyed to 00:00 UTC of the trading date to match every
  other 1d candle.

---

## A2. Repository state — read before committing

Round 1 is committed (`8599b99 Currecny exchanging`, then `3d3f59c`).
**Round 2 (names, i18n, SEO) is entirely uncommitted:**

```
Modified:
  CLAUDE.md  app/config.py  app/main.py  app/models/__init__.py
  app/models/seeder.py  app/routers/market.py  app/schemas/exchange.py
  frontend/index.html  frontend/nginx.conf  frontend/package.json
  frontend/package-lock.json  frontend/tsconfig.app.json
  frontend/src/** (App, AppShell, pages, lib, test handlers, …)
  tests/test_market.py

New:
  app/seo.py  app/i18n/  app/helpers/instruments.py
  app/models/instrument.py  app/routers/instruments.py
  migrations/versions/2026_10_11_1200-0005_instruments.py
  frontend/src/locales/  frontend/src/lib/{i18n,region,market,seo-tags}.ts
  frontend/src/components/{LanguageLayout,LanguageSelect,LocalizedLink,Seo}.tsx
  frontend/src/pages/{MarketsPage,NotFoundPage}.tsx  frontend/src/hooks/useLanguage.ts
  tests: tests/test_instruments.py  tests/unit/test_i18n.py
         tests/unit/test_instrument_catalog.py
         frontend/src/App.test.tsx  frontend/src/lib/{i18n,seo-tags}.test.ts
         frontend/src/locales/locales.test.ts
```

Still untracked from **before** this work, and still needing a commit:
`.env.example`, `docs/` (all four files) and **`requirements.lock`**. The lock
is load-bearing: the Docker image installs from it, and it now pins `yfinance`,
`httpx` and `defusedxml`.

To commit the lot:

```bash
git add app/ migrations/ tests/ frontend/ CLAUDE.md .gitignore \
        .env.example requirements.lock docs/
git status            # confirm no .env, *.db or frontend/dist slipped in
./dev verify          # typecheck + both suites
git commit
```

`frontend/tsconfig.app.tsbuildinfo` shows as modified because it is a build
artefact that happens to be tracked. Committing it is harmless, and so is
`git checkout` on it.

---

## A3. What to do next

1. **Commit Round 2** (§A2).
2. **Migrate and rebuild:**

   ```bash
   ./dev up              # rebuilds images: new Python and npm dependencies
   # migrations run via the tradingmaster-migrate job (0004 + 0005)
   ```

3. **Restart the Flink job once.** Its topic pattern is built from the enabled
   exchanges at start, so it won't store the new `yahoo.*` topics until
   restarted.
4. **Look at it in a browser.** Nobody has yet. Check:
   - `http://localhost:8000/`: on a machine in Poland, it should **redirect to
     `/pl`**, show Polish text, prices in PLN, and a Bitcoin (BTC) heading.
   - Header pickers: switching language keeps the page; switching currency
     re-fetches. Both choices survive a reload.
   - `/markets`: search "orlen", filter Stocks, click through to the market page.
   - `/markets/orlen-pkn-wa` during GPW trading hours: live price in PLN, with
     about a 15-minute delay.
5. **Spot-check what crawlers get:**

   ```bash
   curl -s localhost:8000/pl/markets/bitcoin-btc | grep -E '<html|<title|hreflang|canonical'
   curl -sI localhost:8000/markets/nope | head -1          # 404
   curl -s localhost:8000/sitemap.xml | grep -c '<loc>'     # 476
   curl -s localhost:8000/robots.txt
   curl -s "localhost:8000/api/v1/currencies" | head -c 300 # 30 currencies once ECB loaded
   ```

6. **Production config:** set `SITE_URL=https://<public domain>`. Without it,
   canonical, hreflang and sitemap links use whatever host the request came in
   on, which behind a proxy can be an internal name.
7. **Get the translations reviewed by native speakers**: pl, de, fr, no, it, es.
   They are careful drafts, but drafts. Each language is two files:
   `frontend/src/locales/<lang>.json` (UI) and `app/i18n/locales/<lang>.json`
   (labels and SEO). Tests will fail if a key or `{{placeholder}}` goes missing.

---

## A4. Gotchas from this round

- **Adding a page means two places.** Add the client route in
  `frontend/src/App.tsx` **and** in `STATIC_PAGES` in `app/seo.py`. Otherwise
  the server answers it with a 404 and noindex.
- **UI SEO text must equal server SEO text.** `seo.*` in
  `frontend/src/locales/*.json` is tested to be identical to `seo.*` in
  `app/i18n/locales/*.json`. Change both together.
- **Polish needs four plural forms** (`_one/_few/_many/_other`), and French,
  Italian and Spanish need `_many`. The locale test checks each language against
  `Intl.PluralRules`.
- **Frontend tests pin `TZ=UTC`** (`src/test/setup.ts`). Language and currency
  detection both read the machine's time zone. On a Warsaw machine,
  un-pinned tests would switch to Polish and PLN.
- **No server-side language redirect, on purpose.** Crawlers send no location,
  and Google advises against redirecting on `Accept-Language`. The first-visit
  redirect to `/pl` happens in the browser only.
- **nginx variant:** page requests are now proxied to the API, which renders the
  head; `/assets` is still served statically. If the API is down, nginx falls
  back to the plain shell.
- **`pkill -f "<pattern>"` can kill its own shell** when the pattern appears in
  that shell's command line, as happened here. Kill by PID (§3.1).

---

## A5. Open items added by this round

These are in addition to §6, which is unchanged and still comes first:
**the collector runs inside the API at `replicas: 3`**. It matters more now,
because Yahoo would also be polled three times over.

1. **Yahoo is an unofficial, delayed, SLA-free source.** It's fine for display.
   Before selling stock data, replace it with a licensed feed; the source
   registry (`NON_CCXT_SOURCES`) is the seam for that.
2. **One ECB rate per day.** A stock candle ingested before about 16:00 CET is
   converted with yesterday's rate, and read back later with today's, so a PLN
   stock shown in PLN can be off by that day's rate move.
3. **Translations need native review** (§A3.7).
4. **The UI bundle is 590 kB** (187 kB gzipped). Vite warns about it.
   Code-splitting the chart library is the obvious first cut.
5. **`npm audit` reports 4 findings**, all in dev-only test tooling
   (vitest/tinypool). Nothing ships to users, but upgrade vitest when convenient.

---

# Part B — September 2026 round (earlier work)

## 0. How this started

It began as a review of `docs/BUSINESS_SUMMARY.md` against the actual code —
checking whether what the document claimed was true. **It was.** Every item
marked OK really was done; every item marked Open really was still open. That
document can be taken into a meeting and trusted.

The review did surface one thing the document never mentioned, and it is still
the highest-value open item: **the collector runs inside the API, and production
sets `replicas: 3`** — so everything would be collected three times over. See §6.

Business then signed off three roadmap items plus a security review. That is
what §1 covers.

---

## 1. What was delivered

All verified against a real PostgreSQL, a real Kafka and live exchange data —
not just unit tests.

| # | Item | Where it's written up |
|---|---|---|
| 6 | **Database migrations (Alembic)** — the API now *verifies* the schema is at head and refuses to start otherwise; it no longer creates tables | `migrations/`, README "Database migrations" |
| 8 | **Nightly archive is safe to re-run** + 9 alert rules + Alertmanager | `app/jobs/eod_archive.py`, `observability/prometheus/rules/` |
| 11 | **Live stream scales, API is protected** — shared Kafka consumer hub, rate limits, bounded inputs | `app/kafka/stream_hub.py`, `app/middleware/` |
| 19 | **The one Polish error message is now English**, with a test pinning it | `app/routers/market.py`, `tests/test_api_protection.py` |
| S | **OWASP Top 10 audit** — 26 findings, 22 fixed | **`docs/SECURITY_AUDIT.md`** |
| — | **Local development setup** — the whole stack runs in Compose, API included | **`docs/LOCAL_DEVELOPMENT.md`** |
| — | **Content-addressed images** — a stale image can no longer be started silently | `dev`, `scripts/image-tag.sh`, §4 |

Roadmap #19 is worth a note: it was **already fixed but still marked Open** in
the business summary. Checking each row against the code caught it. The summary
now says OK, and the delivered count was corrected from eleven to twelve.

**Tests: 424 backend + 96 frontend, all passing.** 5 backend tests are skipped —
they're the migration tests, which need a real PostgreSQL (`TEST_POSTGRES_URL`).

### Bugs found while building this, not just features added

Worth knowing these existed, because each was silent:

- The archive's **retention step deleted a day's prices even when its archive
  had failed** — so a failed run cost you the data anyway.
- **`--replace` could destroy an archive it had no way to rebuild** (the source
  candles having already aged out). It now refuses and exits 3.
- Archive **row counts were wrong on PostgreSQL** — `rowcount` returns `-1` for
  an executemany insert, so the first run reported "0 archived" having archived
  500. SQLite reports it correctly, which is why tests passed. Now counted with
  `RETURNING`.
- **Two `.env` files were fighting**, so the API and its own migrations pointed
  at different databases depending on the entry point. See §5.

---

## 2. Repository state — read this before committing

> **Superseded by §A2.** `dev`, `Makefile`, `scripts/image-tag.sh` and the
> Compose changes have since been committed. Only `.env.example`, `docs/` and
> `requirements.lock` from the list below are still untracked. Kept for history.

You already committed the bulk of it as `23ad84a`. **What's still uncommitted is
this session's local-dev and Compose work**, and two of those files are not
optional:

```
Modified:
  app/config.py                        .env loading fix (see §5)
  docker-compose.yml                   the api service + content-addressed tags
  observability/prometheus/prometheus.yml   scrape api:8000, not the host
  frontend/Dockerfile                  default API_HOST -> api:8000
  frontend/src/test/fake-websocket.ts  TypeScript build fix
  .gitignore  README.md  CLAUDE.md

Untracked — all of these need committing:
  requirements.lock      ⚠️  THE DOCKER BUILD INSTALLS FROM THIS
  dev                    the entry point script
  scripts/image-tag.sh   content hashing for image tags
  Makefile               thin wrapper around ./dev
  .env.example           documents every setting
  docs/                  all four documents, never committed
```

> ⚠️ **`requirements.lock` is load-bearing.** `Dockerfile` runs
> `pip install --require-hashes -r requirements.lock`. Clone the repo without
> it and the image build fails. Same for `dev` and `scripts/image-tag.sh` —
> without them `./dev` doesn't exist.

Local-only, correctly gitignored, do not commit: `.env`, `.env.backup-*`,
`app/.env.unused-backup`, `data/`, `*.db`.

To commit the lot:

```bash
git add .gitignore CLAUDE.md README.md app/config.py docker-compose.yml \
        frontend/Dockerfile frontend/src/test/fake-websocket.ts \
        observability/prometheus/prometheus.yml \
        .env.example Makefile dev scripts/image-tag.sh requirements.lock docs/
git status            # confirm no .env or *.db slipped in
git commit
```

Sanity check before you push — a fresh clone must be able to build:

```bash
./dev verify          # typecheck + both suites
./dev stale           # images match the source
```

---

## 3. What to do next

### 3.1 Port 8000 — resolved, but read this if it recurs

This is sorted: the stack is on the normal `:8000`.

It's worth knowing *why* it was stuck, because `pkill -f "uvicorn app.main:app"`
**does not work** and I gave you that command first time round. Sorry.

When `uvicorn --reload` runs, the process doing the actual serving is a
`multiprocessing` **child**, and its command line looks like this:

```
env/bin/python -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=5, pipe_handle=7)
```

No "uvicorn" in it, no "app.main". So a pattern kill matches the parent, the
parent dies, and the child is reparented to systemd and carries on holding the
socket — in this case for three hours. `ps aux | grep uvicorn` finds nothing
either, which makes it look like the port is held by a ghost.

**Find the real owner by the port, never by the process name:**

```bash
ss -ltnp | grep :8000
#   LISTEN 127.0.0.1:8000   users:(("python",pid=7088,fd=3))
kill 7088
```

If `ss` won't show you the PID, use `sudo ss -ltnp` or `sudo lsof -i :8000`.

Same technique for any "address already in use": identify by port, then kill the
PID. The equivalent for a container-held port is
`docker ps --format '{{.Names}} {{.Ports}}' | grep 8000`.

### 3.2 Then run through the manual test

Everything below was verified working — if something differs, that's a real
regression, not a setup problem.

**Start**

```bash
./dev up
./dev ps             # 12 services; tradingmaster-migrate at "Exited (0)" is CORRECT
```

**Core API**

```bash
curl http://localhost:8000/health                       # {"status":"ok"}
curl -s http://localhost:8000/api/v1/market/markets     # "Found 65 market(s)" since Part A (was 20)
open http://localhost:8000                              # the UI
open http://localhost:8000/docs                         # Swagger
```

**Live stream** — pick a market on the Live screen; candles should appear within
seconds. Check the raw-feed panel shows `BTC/USD` with `source_ticker: BTC/USDT`
and an `fx_rate` near 0.999 — that's the unified feed converting Binance's USDT
quote to USD at the live Kraken rate.

**Persistence** (give Flink ~2 minutes after start)

```bash
docker exec tradingmaster-postgres psql -U user -d tradingmaster \
  -c "select exchange, interval, count(*) from candles group by 1,2 order by 3 desc limit 5"
```

If the live stream works but this stays empty, Flink is the problem — the live
stream reads Kafka directly, only Flink writes to the database.

**Auth** — register on the Login screen. Note the password rules: **12+
characters, and it must not contain your email's local part.** `dev@example.com`
with `local-dev-password-123` is rejected because the password contains `dev`.
That's the policy working, not a bug.

**Archive idempotency** — the headline fix from item 8:

```bash
./dev archive 2026-10-03 --dry-run
./dev archive 2026-10-03     # e.g. "1970 archived, 1252 already present"
./dev archive 2026-10-03     # re-run: "0 archived, N already present"
```

Row count must not grow on the second run. Before this work, it doubled.

**Protection** — all of these should be rejected:

```bash
curl -o /dev/null -w "%{http_code}\n" "http://localhost:8000/api/v1/market/candles/BTC%2FUSD?limit=99999999"   # 422
curl -o /dev/null -w "%{http_code}\n" "http://localhost:8000/api/v1/history/BTC%2FUSD?date_from=0001-01-01&date_to=9999-12-31"  # 422
for i in $(seq 1 25); do curl -s -o /dev/null -w "%{http_code} " -X POST \
  http://localhost:8000/api/v1/auth/jwt/login -d 'username=a@b.com&password=xxxxxxxxxxxx'; done   # ends in 429
```

**Security headers**

```bash
curl -sI http://localhost:8000/ | grep -i -E "content-security-policy|x-frame"
curl -sI http://localhost:5174/ | grep -i content-security-policy    # nginx variant
```

**Observability**

- <http://localhost:9090> → Status → Rules → **9 alert rules in 3 groups**
- <http://localhost:9090> → Status → Targets → `fastapi` and `flink` both `up`
- <http://localhost:3000> Grafana (`admin`/`admin`) → "TradingMaster Overview",
  default range is 7 days so the once-daily archive is visible
- <http://localhost:9093> Alertmanager — receiver is a deliberate no-op

---

## 4. How to run it, day to day

```bash
./dev up          # everything in Docker
./dev infra       # only Postgres + Kafka + migrations; run the app on your host
./dev help        # all commands
./dev verify      # typecheck + both test suites
```

**Use `./dev`, not `docker compose` directly.** Compose starts whatever image
carries the tag it asks for and never looks at your source, so it will silently
run a stale build. That happened twice here: a Flink image from before the
unified-feed rename died on `binance.BTCUSDT.candles`, and a frontend image from
before the nginx change served the app **with no security headers and no error**.

`scripts/image-tag.sh` hashes all 130 build-input files; `./dev` passes that hash
as the image tag. Changed source → new tag → no such image → Compose must build.
`./dev stale` reports drift, `./dev clean-images` prunes old tags.

---

## 5. Gotchas that cost real time — don't rediscover these

**Two `.env` files used to fight.** `load_dotenv()` searches upward from the
*calling file*, so `app/.env` shadowed the repo-root `.env` — but only for some
entry points. `uvicorn` read the root one, `alembic` read `app/.env`. **The API
and its own migrations pointed at different databases.** Fixed: `app/config.py`
now loads the root `.env` by explicit path. The old file is parked at
`app/.env.unused-backup`; delete it when you're comfortable.

**A green test suite does not mean it compiles.** Vitest transpiles TypeScript
without typechecking. `npm run test:run` passed while `npm run build` failed on
TS2353, which broke the Docker build. Run `./dev typecheck` before `./dev up`.

**`localhost` means "this container" inside a container.** Services talk over
the Compose network: `postgres:5432`, `api:8000`, and Kafka on **`kafka:29092`**
— a different port from the `localhost:9092` your laptop uses. Compose sets
these; it only matters if you add a service yourself.

**`tradingmaster-migrate` showing `Exited (0)` is success**, not a failure. It's
a one-shot job that applies migrations and exits. `Exited (1)` is the bad one.

**`grep` exits 1 when it matches nothing.** Under `set -euo pipefail` that kills
a script. Bit me in `./dev clean-images` — it removed one image then stopped
silently.

---

## 6. Open items, highest value first

Full detail in `docs/SECURITY_AUDIT.md` §5.

1. **The collector runs inside the API, and production sets `replicas: 3`** —
   three copies of every exchange stream and every Kafka message. Cost, and a
   risk of exchange rate-limiting. `app/producer_runner.py` already exists as a
   standalone entrypoint; it needs its own Deployment at `replicas: 1` and
   removal from the API lifespan. **~1 day, and it should happen before any
   production deploy.** Audit ref A04-5. Not yet a numbered roadmap item —
   say the word and I'll add it.
2. **No admin role** (roadmap #4). Any registered user can pause exchanges and
   insert prices. `current_superuser` exists and is used on no endpoint.
   Mutating endpoints now log the acting user id, so actions are at least
   attributable.
3. **Open registration** — accounts are active immediately, `is_verified` is
   never required. Gating it needs an email backend (roadmap #14).
4. **Durable archive storage** (roadmap #2). `PARQUET_BASE_DIR` is now a setting
   rather than hardcoded, and Compose has an `archive_data` volume — but in
   Kubernetes the files still land on the Job pod's ephemeral disk and are lost.
5. **TimescaleDB is not actually enabled** (roadmap #7) — plain `postgres:16`,
   no hypertable, compression or retention policy, despite the name.

---

## 7. Document map

| File | For whom | What it answers |
|---|---|---|
| `docs/BUSINESS_SUMMARY.md` | Business | What the platform does, the roadmap, what's delivered (§9 roadmap, §13 September, §14 currencies and stocks, §15 names, languages and SEO) |
| `docs/SECURITY_AUDIT.md` | A security reviewer | OWASP Top 10, evidence per finding, fixed vs tracked, how to re-verify |
| `docs/LOCAL_DEVELOPMENT.md` | You, day to day | Full setup, both run modes, troubleshooting |
| `docs/HANDOFF.md` | You, coming back cold | This file — what happened and what's next |
| `README.md` | Anyone cloning | Repo overview; now leads with `./dev up` |
| `CLAUDE.md` | Agents working here | Architecture, known gaps, why `./dev` not `docker compose` |

All four `docs/` files are **untracked**. See §A2.
