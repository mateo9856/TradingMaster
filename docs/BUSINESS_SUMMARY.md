# TradingMaster — Business Summary

*An engineering overview for business stakeholders: what the platform does, how it works, what it is built on, and what we recommend improving next.*

---

## 1. Executive summary

TradingMaster is a **real-time cryptocurrency market-data platform**. It connects to three major exchanges (**Binance, Kraken and Coinbase**) and collects price data for about **50 trading pairs**, at five candle lengths: **30 seconds, 1 minute, 5 minutes, 1 hour and 1 day**. It stores the data, archives it daily for long-term use, and makes it available to other systems and people through an API and a live data stream. Every price is published in **one unified format: US dollars, as exact decimal numbers**, whichever exchange it came from.

In short: **one place to get clean, uniform crypto price data from several exchanges, both live and historical.**

**Current state:** the full data pipeline works end to end — collection, transport, storage, daily archiving, API, user login, monitoring and deployment configuration are all in place and covered by automated tests. The platform is at an **MVP / pre-production** level: the foundations are solid, but a handful of issues (listed in the roadmap in section 9) should be fixed before we rely on it for production or paying customers.

**Update (September 2026):** twelve business requests have been delivered (see sections 11, 12 and 13):
- the storage job now **resumes where it stopped**, so downtime no longer creates gaps
- markets added through the API are now **saved as well as collected**
- the market list is **loaded from the database** everywhere
- **many more trading pairs** are tracked
- **more candle lengths** are available (30 seconds, 1 minute, 5 minutes, 1 hour, 1 day)
- there is a **unified USD price feed**
- there is now a **web interface (MVP)** — the platform can be seen and clicked, not just described

And in a second round (section 13):
- **database changes are now a managed, versioned step** instead of manual SQL
- the **nightly archive is safe to re-run**, and now **raises alerts** when it fails or falls behind
- the **live stream scales with markets, not with viewers**, and the API is protected against overload
- the one **error message that was in Polish** is now in English
- a full **OWASP Top 10 security review** was completed — 22 of 26 findings fixed (see [SECURITY_AUDIT.md](SECURITY_AUDIT.md))

They are marked **OK** in the roadmap.

**Update (October 2026, second round):** every market now says **what it is** ("Bitcoin — a cryptocurrency", "ORLEN S.A. — a listed company, energy sector, Warsaw Stock Exchange"), there is a searchable **directory of all markets**, the interface speaks **7 languages** (English, Polish, German, French, Norwegian, Italian, Spanish) chosen by the visitor's location, and every market has its own **search-engine-ready page** (section 15).

**Update (October 2026):** prices can now be shown in **30 local currencies** (złoty, euro, kroner, …), and the interface opens in the currency of the country it runs in. **25 company stocks** (US, Warsaw, Frankfurt, Oslo) and **50 more coins** were added (section 14).

---

## 2. What problem it solves — business cases

Every exchange publishes prices in its own format, through its own connection style, with its own quirks. Anyone who wants to build a chart, a trading strategy or a report across exchanges first has to solve this "plumbing" problem. TradingMaster solves it once, centrally.

| Business case | How TradingMaster supports it |
|---|---|
| **Unified market feed** | Prices from Binance, Kraken and Coinbase arrive in one identical format, regardless of source: **every price is in US dollars** and written as an exact decimal number with 8 decimal places (e.g. `65000.10000000`). Bitcoin is `BTC/USD` on every exchange, even where the exchange itself trades it against the USDT or USDC stablecoin. |
| **Live dashboards and trading front-ends** | A live stream (WebSocket) pushes new prices to a screen or app the moment they arrive — no refreshing. |
| **Charts of recent activity** | A simple API returns the most recent price candles at 30-second, 1-minute, 5-minute, 1-hour or 1-day resolution (the last 7 days are kept "hot" for fast access). |
| **Backtesting and machine learning** | Every day, the previous day's data is exported to Parquet files — the standard format for data science tools — and kept in a long-term history table. Strategies can be tested against real past data. |
| **Cross-exchange comparison / arbitrage monitoring** | The same coin (e.g. BTC) is tracked on several exchanges side by side, **in the same currency (USD)**, so price differences between exchanges can be compared directly. |
| **See the platform working** | A web interface shows live prices with a chart, the archive, and the health of the pipeline — no technical tools needed. |
| **Self-service market coverage** | New coins can be added (one by one or many at once), enabled or paused through the API, without a developer changing code. The change is collected and saved automatically within about a minute, with no restart. |

**Currently tracked markets (defaults):**

| Exchange | Markets (the exchange's own pair; all published as `COIN/USD`) |
|---|---|
| Binance (20) | BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, DOT, LINK, LTC, TRX, POL, SHIB, UNI, ATOM, XLM, BCH, NEAR, APT — all against USDT |
| Kraken (16) | BTC, ETH against USDT; SOL, XRP, ADA, DOGE, DOT, LINK, LTC, AVAX, ATOM, XLM, BCH, UNI, TRX, NEAR against USD |
| Coinbase (15) | BTC, ETH, SOL, XRP, ADA, DOGE, AVAX, DOT, LINK, LTC, BCH, UNI, ATOM, XLM, SHIB — all against USD |

Every market is collected at **30 seconds, 1 minute, 5 minutes, 1 hour and 1 day** (previously: 7 markets, 1 minute only).

---

## 3. Key concepts (glossary)

- **Candle (OHLCV)** — a summary of trading in one time window (here: 30 seconds up to 1 day). It holds five numbers: **O**pen price, **H**ighest price, **L**owest price, **C**lose price and **V**olume traded. Candles are what trading charts are drawn from.
- **Ticker / symbol** — the name of a trading pair, e.g. `BTC/USDT` = Bitcoin priced in the Tether stablecoin (≈ US dollar).
- **Interval** — the length of one candle. Supported: **30 seconds, 1 minute, 5 minutes, 1 hour, 1 day**.
- **Stablecoin (USDT, USDC)** — a crypto token designed to be worth one US dollar. Many exchanges price coins in stablecoins rather than in real dollars.
- **Unified ticker** — the single name a coin has in our feed, always priced in USD (`BTC/USD`), no matter whether the exchange trades it against USD, USDT or USDC. The exchange's own name is kept alongside it (`source_ticker`).
- **FX rate (conversion rate)** — the live price of a stablecoin in US dollars (e.g. 1 USDT = 0.9997 USD), used to convert stablecoin prices to USD. It is stored with every candle for auditability.
- **Exchange** — a marketplace where crypto is traded (Binance, Kraken, Coinbase).
- **Hot vs. cold data** — *hot* data is recent and accessed often (kept in the main table for 7 days); *cold* data is older, rarely changed, and stored in the history table and archive files.
- **Streaming vs. batch** — *streaming* processes each piece of data the moment it arrives; *batch* processes a whole chunk at once (e.g. the nightly archive).

---

## 4. How it works — the data journey

```text
 Binance ─┐                 unified USD
 Kraken  ─┼─► 1. Collector ─────────────► 2. Kafka ─┬─► 3. Flink ─► Database (hot, 7 days) ─► 5. Nightly archive ─► History table + Parquet files
 Coinbase─┘    (CCXT Pro,   format        (message   │   (storage,           │
               + USD rates)                bus)      │    resumes)           └─► 4. REST API (recent candles, history)
                                                     └─► 4. Live WebSocket stream (real-time)
```

### Step 1 — Collection
A collector service keeps a permanent connection open to each exchange and receives price updates as they happen. Each exchange needs a slightly different approach, and the platform handles all three:

- **Binance** — sends ready-made candles for several coins over one connection.
- **Kraken** — sends ready-made candles, one connection per coin.
- **Coinbase** — only sends individual trades, so TradingMaster **builds the candles itself** by grouping trades into time windows.

Where an exchange offers a candle length itself (e.g. 1 minute, 1 hour), it is used directly. Where it doesn't (**30 seconds** on every exchange, and every length on Coinbase), TradingMaster builds it from the individual trades.

Before a candle is sent on, it is converted to the **unified format**:
- the coin gets its unified USD name
- stablecoin prices are converted to US dollars at the **live** USDT/USD or USDC/USD rate, taken from Kraken
- all numbers are written as exact decimals

If no fresh conversion rate is available (e.g. for the first seconds after a start), the 1:1 dollar peg is used and this is counted on the monitoring dashboard.

The collector re-reads the market list from the database **every minute**, so markets added or paused through the API take effect without a restart. A pair that an exchange doesn't list is skipped with a warning instead of disrupting the other pairs. If a connection drops or an exchange returns an error, the collector **automatically reconnects after 5 seconds**. No exchange account or API key is needed — this is public market data.

### Step 2 — Transport (Kafka)
Every candle is published to **Kafka**, a high-throughput "message bus". Each exchange + coin combination has its own channel (e.g. `binance.BTCUSD.candles`), which carries all candle lengths for that coin. This separates *collecting* data from *using* it: storage, the live stream and any future consumer (alerts, analytics) can all read the same feed independently, and a slow consumer never slows down collection.

### Step 3 — Storage (Apache Flink)
A stream-processing job (**Apache Flink**) reads the candles from Kafka and writes them to the database. It writes in small batches (up to 100 rows or every 5 seconds) for efficiency, and retries on failure. Because exchanges send updates for the *current* candle several times as it develops, the job **updates the existing row instead of creating duplicates** — the database always holds exactly one, most up-to-date candle per exchange, coin, candle length and time window.

- **Every market is saved.** The storage job takes its market list from the database and automatically discovers new markets (checked every minute). A coin added through the API is therefore saved, not just shown on the live stream.
- **Resumes where it stopped.** The job regularly records how far it has read (a "checkpoint", every 30 seconds). After a stop, crash or redeploy it **continues from that point**, so candles produced while it was down are caught up and written. There are no permanent gaps, as long as the outage is shorter than Kafka's 7-day retention. This was verified by stopping the job, producing data, and restarting it: all data arrived, with no duplicates.

### Step 4 — Serving the data
- **Recent candles API** — e.g. "give me the last 100 five-minute BTC/USD candles from Binance". Clients may write the coin as `BTC/USD`, `BTC/USDT` or `BTCUSDT`; all mean the same unified market.
- **History API** — archived candles for any date range.
- **Live stream (WebSocket)** — a client subscribes to a coin (optionally one exchange) and receives each new candle instantly.
- **Interactive documentation** is built in (`/docs`, `/redoc`), so integrators can explore and try the API in a browser.

### Step 4b — The web interface
A browser dashboard (see section 12) sits on top of the same public API. It is the quickest way to confirm the whole chain works: choose a coin, watch its candles update live, and read the raw message the platform publishes.

### Step 5 — Nightly archive (End-of-Day job)
Once a day (scheduled for 23:30 UTC in Kubernetes), a separate job:
1. Copies **yesterday's** candles into the long-term **history table**.
2. Exports them to **Parquet files**, one file per exchange, coin and day — ready for data science and backtesting.
3. **Deletes data older than 7 days** from the hot table, keeping it small and fast.

The job runs independently of the API, so an API restart can never cause a day to be skipped. A missed or past day can also be archived on demand ("backfill") through an API call.

### Market configuration
The list of exchanges, coins and candle lengths lives in the database, not in code. The collector, the storage job and the live stream all read it from there. On every start the system adds any missing defaults (section 2) without touching existing settings. Authorised users can add coins one at a time or many at once (every coin × every candle length in one request), and switch them on or off via the API. The API rejects anything the unified feed can't publish:
- a coin not priced in USD, USDT or USDC
- an unsupported candle length
- a second market for the same coin on the same exchange

Changes take effect within about a minute, with no restart. Adding a completely new *exchange* still needs a restart of the storage job.

---

## 5. Access and security

- **Reading data is public** — all read endpoints and the live stream require no login.
- **Changing anything requires login** — adding/pausing exchanges or coins, manually inserting a candle, and triggering an archive run all require a logged-in, active user.
- **User accounts** — registration, login (secure time-limited sessions, 1 hour by default), logout, password reset and email verification flows exist, plus self-service profile and admin user management.
- **Browser sessions are held in a protected cookie** (September 2026). When someone signs in through the web interface, the proof of identity is stored by the browser in a form the page's own code cannot read, so a flaw in the interface — or in one of the open-source libraries it uses — cannot be used to steal a session. The cookie is never sent to other websites, and any action that changes data must carry an extra marker that only our own interface can add. Programs and scripts that use the API keep using the previous token-based method, which was never exposed to this risk.
- **Gaps today:** anyone can register, and every registered user has full change rights (no admin vs. regular user distinction). Password-reset and verification emails are not actually sent yet (no email provider connected). See roadmap.

---

## 6. Monitoring and operations

The platform has a strong operational foundation — better than typical for this stage:

- **Metrics & dashboards** (Prometheus + Grafana) — messages collected per exchange/coin, reconnect counts, live-stream viewers, API traffic and speed, archive job success/failure and duration. A ready-made "TradingMaster Overview" dashboard is included.
- **Tracing** (Jaeger / OpenTelemetry) — each candle can be followed from the moment it was received from the exchange to the database row it ended up in. Useful when investigating "why does this price look wrong?".
- **Centralised logs** (Loki) — structured logs from all components, searchable in Grafana and linked to traces.
- **Deployment** — runs locally with Docker Compose and in production-style environments with Kubernetes (separate local and production configurations).
- **Automated tests** — unit, API and integration tests that run without any external infrastructure, so they are cheap to run on every change.

---

## 7. Technology stack

| Technology | Role in TradingMaster | Why it is a good business choice |
|---|---|---|
| **Python + FastAPI** | Core application and API | Fast to develop, widely known, automatic API documentation. |
| **CCXT Pro** | Connecting to exchanges | One library for 100+ exchanges — adding a new exchange is mostly configuration, not new integration work. |
| **Apache Kafka** | Message bus between components | Industry standard for real-time data; scales to very high volumes; lets new consumers plug in without touching existing ones. |
| **Apache Flink** | Stream processing into the database | Built for reliable, continuous data processing; checkpoints let it resume exactly where it stopped; room to grow into real-time analytics. |
| **PostgreSQL** (TimescaleDB planned) | Database | Proven, open-source, no licence cost. TimescaleDB is an extension specialised for time-series data like prices. |
| **Parquet** (via pandas) | Daily archive files | Compact, fast, and readable directly by data science and ML tools. |
| **FastAPI Users + JWT** | User accounts and login | Standard, well-maintained authentication building blocks. |
| **React + TypeScript (Vite)** | Web interface | The most widely used front-end stack — easy to hire for, huge component ecosystem, and it ships as plain static files, so it adds no new server to run. |
| **TradingView lightweight-charts** | Price charts | Purpose-built for candle charts with live updates; the chart style traders already know; free and very small. |
| **Prometheus, Grafana, Jaeger, Loki** | Monitoring, dashboards, tracing, logs | Open-source standard observability stack; no licence cost. |
| **Docker + Kubernetes** | Packaging and running the system | Same setup from a laptop to the cloud; scalable and cloud-provider neutral. |

The whole stack is **open source**, so there are no software licence fees — costs are infrastructure and engineering time.

---

## 8. Current limitations (honest status)

- ~~Some parts of the configuration are still **fixed in code**: markets added through the API are collected, but not saved to the database until the storage job is updated.~~ **OK — fixed (2026-09):** the market list comes from the database, and new markets are saved automatically.
- A few scenarios can cause **silent data loss or gaps**. ~~Storage job downtime~~ is **OK — fixed (2026-09)** (the job resumes where it stopped); archive files in Kubernetes and Coinbase restarts remain.
- **Access control is too broad** — any self-registered user can change configuration or insert prices. Who did what is now recorded, but not yet restricted.
- The database is plain PostgreSQL; the time-series extension (TimescaleDB) the design assumes is **not actually enabled yet**.
- Some settings are single-server/dev-grade (message bus without redundancy, no email provider). ~~No database migration tooling.~~ **OK — fixed (2026-09).**
- ~~Only **1-minute** candles are produced.~~ **OK — fixed (2026-09):** 30 seconds, 1 minute, 5 minutes, 1 hour and 1 day.
- ~~**Only dollar-priced markets** (USD, USDT, USDC) can be tracked.~~ **OK — fixed (2026-10):** markets quoted in euro, złoty and 28 other currencies can be collected, and every price can be *shown* in any of 30 currencies (section 14). Crypto-to-crypto pairs such as ETH/BTC are still rejected.
- **Stock prices are delayed about 15 minutes** and come from Yahoo Finance's free, unofficial interface (section 14). Fine for display and research; a licensed real-time feed would be needed before selling stock data.
- **USD conversion falls back to the 1:1 peg** when no fresh USDT/USD or USDC/USD rate is available. This is visible on the dashboard; the error is normally below 0.1%.
- **Data collected before September 2026** was relabelled to the unified USD names by a one-off migration at a 1:1 stablecoin rate, because the real rate at the time was not recorded.
- Candles built from trades (all Coinbase candles and all 30-second candles) are only sent once the time window has closed, and the window in progress is lost on a collector restart (see roadmap #9).

None of these are design flaws — they are typical MVP shortcuts. They are all addressed in the roadmap below.

---

## 9. Recommendations roadmap

Effort: **S** = days, **M** = 1–2 weeks, **L** = several weeks (one engineer, rough estimate).

### NOW — data safety and trust (before production use)

| # | Recommendation | Why it matters for the business | Risk if ignored | Effort | Status |
|---|---|---|---|---|---|
| 1 | **Make the storage job read the market list from configuration** instead of a fixed list in code. | Delivers the promised "add a market without a developer". | A newly added coin appears on the live stream but is **never saved** — history and archives for it are silently empty. | M | **OK** (2026-09) |
| 2 | **Store archive files in durable storage** (cloud object storage such as S3/GCS, or a persistent disk). | Parquet archives are the core asset for backtesting/ML. | In Kubernetes the files are written to the job's temporary disk and **deleted when the job ends**. | S | Open — the location is now a setting (`PARQUET_BASE_DIR`) rather than fixed in code, so only the storage itself still needs attaching |
| 3 | **Let the storage job resume where it stopped** (resume from last processed position + enable Flink checkpoints). | Complete, gap-free history. | ~~If the storage job is down for 10 minutes, those 10 minutes are permanently missing.~~ Now caught up on restart. | S–M | **OK** (2026-09) |
| 4 | **Introduce an admin role** for configuration changes and manual price inserts; restrict open registration. | Data integrity and trust in the numbers. | Any person who registers can pause exchanges or **insert fake prices**. | S | Open |
| 5 | **Harden production secrets** — unique signing key, passwords in a secrets manager instead of plain-text Kubernetes config files (production currently has placeholder values there). | Basic security hygiene expected by customers and auditors. | Account takeover / unauthorised access if defaults leak to production. | S | Open |

### NEXT — reliability and scale (next 1–2 quarters)

| # | Recommendation | Why it matters for the business | Effort | Status |
|---|---|---|---|---|
| 6 | **Database migration tooling** (Alembic) | Safe, repeatable database changes on every release. | M | **OK** (2026-09) |
| 7 | **Enable TimescaleDB** (compression, automatic retention, fast time-range queries) | Lower storage cost and faster queries as history grows into years of data — now more pressing, as ~50 pairs × 5 candle lengths produce much more data. | M | Open |
| 8 | **Make the nightly archive safe to re-run + add alerting** (failed runs, stale data) | Re-runs are now harmless, and failures raise an alert instead of going unnoticed. | S–M | **OK** (2026-09) |
| 9 | **More robust trade-built candles** (Coinbase, and all 30-second candles) | Today the window in progress is lost on restart, quiet windows (no trades) produce no candle, and the last candle is only sent when the next trade arrives. | M | Open |
| 10 | **Apply configuration changes without a restart** | ~~Enabling/disabling a market via the API only takes effect after the collector restarts.~~ The collector re-reads the configuration every minute (configurable). | M | **OK** (2026-09) |
| 11 | **Scale the live stream and protect the API** (shared stream hub, rate limits, max page size) | The live stream's cost no longer grows with the audience, and the API can't be overloaded by one client. | M | **OK** (2026-09) |
| 12 | **Production-grade Kafka settings** (redundancy, multiple partitions) | Today a single broker failure stops the whole data flow. | S | Open |
| 13 | **Exact decimal prices** instead of floating-point numbers | Financial data should not have rounding artefacts (e.g. 0.1 + 0.2 ≠ 0.3). ~~Floats~~ → exact 8-decimal numbers everywhere (part of the unified feed). | S–M | **OK** (2026-09) |
| 14 | **Connect an email provider** | Password reset and email verification actually reach users. | S | Open |

### LATER — product growth

| # | Recommendation | Business value | Status |
|---|---|---|---|
| 15 | **Higher timeframes** (5 min, 1 hour, 1 day) | Standard chart views customers expect; much faster long-range queries. | **OK** (2026-09) — 30 s, 1 min, 5 min, 1 h, 1 day; taken directly from the exchange where offered, otherwise built from trades |
| 16 | **More exchanges and coins** | Broader market coverage; low effort thanks to CCXT once item 1 is done. | **OK** for coins (2026-09, 2026-10) — 7 → 51 → 101 crypto markets, plus 25 stocks; more exchanges remain open |
| 17 | **Data quality checks** — gap detection, sanity rules (e.g. high ≥ low), cross-exchange outlier detection | Trustworthy data as a selling point — easier now that all exchanges share one currency and format. | Open |
| 18 | **API keys, usage tiers and quotas** | Foundation for monetising the data (free vs. paid plans, B2B access). | Open |
| 19 | **Consistent API language and messages** | Professional, predictable experience for integrators. | **OK** (2026-09) — the one Polish error message is now in English, and a test keeps it that way |
| 21 | **Market management in the web interface** — add, pause and bulk-add coins from the UI instead of the API | **TODO — the main gap in the MVP interface.** Today the screens read data; adding or pausing a market still needs a developer or an API tool, which is exactly the self-service promise from section 2. | Open |
| 22 | **Charts of several exchanges side by side** | Cross-exchange differences become visible at a glance, not just as one latest price each. | Open |
| 20 | **Service-level targets (SLAs)** — uptime, data freshness, completeness | Needed for paying customers and internal accountability. | Open |

---

## 10. Suggested next step

Two of the five **NOW** items (#1 and #3) are done, and the September second round closed #6, #8 and #11 plus the security review.

The single highest-value piece of work now is one the review surfaced and which is **not yet on the roadmap**: the price collector runs inside the API, and production runs three copies of the API — so everything is collected three times over. About a day's work, and it should happen before any production launch (section 13).

After that, the remaining **NOW** items — **durable archive storage (#2), an admin role (#4) and production secrets (#5)** — are the next sprint (roughly 1–2 weeks for one engineer). Together they close the gap between "works in a demo" and "data we can trust and put in front of customers". With ~7× more markets and 5 candle lengths, **enabling TimescaleDB (#7)** should follow soon after. On the interface side, **market management (#21)** is the one screen that would complete the self-service promise. After that, the **NEXT** items can be prioritised based on which business case — live dashboards, backtesting/ML, or selling data access — is most important to the business.

---

## 11. Delivered changes (September 2026)

Business requests from September 2026 and how they were delivered. **OK** = done.

| # | Business request | Status | What was done | Business effect |
|---|---|---|---|---|
| 1 | **Storage job must resume where it stopped** (ASAP) | **OK** | The storage job (Flink) saves a checkpoint every 30 seconds and records how far it has read in Kafka. After any stop it continues from that point instead of "from now". Transient database or Kafka problems restart the job automatically. | Downtime no longer creates permanent gaps: data from the outage is caught up on restart (up to 7 days back), with no duplicates. Verified end-to-end. Also fixed a compatibility problem that stopped the storage job from starting on Flink 2.3. |
| 2 | **Markets added through the API must be saved, not just collected** | **OK** | The storage job subscribes to every market of the enabled exchanges and checks for new ones every minute. The collector re-reads the market list every minute (configurable). | A coin added through the API is collected **and** saved within about 2 minutes, with no restart and no developer. |
| 3 | **Market list loaded from the database, not hardcoded** | **OK** | The collector already read its list from the database (**OK – already in place**). Now the storage job and the live stream do too. The fixed lists in code and settings were removed. | One place to manage markets; nothing can drift out of sync. |
| 4 | **Many more trading pairs** | **OK** | Default coverage grew from 7 to **51 markets** (20 Binance, 16 Kraken, 15 Coinbase). All were checked against the exchanges' live market lists. There's a new "bulk add" API (many coins × many candle lengths in one request), and existing databases get the new pairs automatically on the next start. | Much broader market coverage, and more can be added by the business itself. |
| 5 | **More candle lengths: 5 min, 1 hour, 1 day, and 30 seconds if possible** | **OK** (incl. 30 s) | Each market is collected at **30 s, 1 min, 5 min, 1 h and 1 day**. The exchange's own candles are used where offered; otherwise candles are built from individual trades (30 s everywhere, all lengths on Coinbase). The database now stores several lengths side by side. | Standard chart resolutions, plus a high-resolution 30-second view. |
| 7 | **A user interface to see the whole process working** | **OK** | An MVP web dashboard: live chart, archive, system health and sign-in. Runs against the real pipeline. See section 12. | Business can demonstrate and sanity-check the platform without technical tools. Market management from the UI is deliberately left for the next step (roadmap #21). |
| 6 | **Unified market feed: prices in the same unified format for all markets** | **OK** | **Same currency:** every price is in **US dollars**; USDT/USDC prices are converted at the live rate from Kraken, and the rate used is stored with each candle. **Same number format:** exact decimals with 8 decimal places everywhere (database, message bus, API, live stream), with no floating-point rounding. **Same naming:** `BTC/USD` on every exchange, with the exchange's own pair kept for reference. | Prices from different exchanges can be compared directly, and the numbers are exact. Also delivers roadmap item #13 (exact decimal prices). |

**Operational notes for this release**
- **Running the interface:** it is built from source (`npm run build`) and then served by the platform itself, or as its own small container — see the README.
- **One-off database migration:** existing databases must run `scripts/migrations/2026_09_unified_feed.sql` once. It is safe to run more than once. It relabels existing history to the unified USD names at a 1:1 stablecoin rate.
- **API change for integrators:** prices in API responses are now **text with 8 decimals** (`"65000.10000000"`) instead of plain numbers, and tickers are the unified USD names (`BTC/USD`). Old spellings like `BTC/USDT` are still accepted in requests.
- **Tests:** every change is covered by automated tests for both success and error cases (305 tests in total, up from 59). The new behaviour was also checked against a real database, a real Kafka broker, the real storage job, and live exchange data.

---

## 12. The web interface (MVP, September 2026)

**The request:** business could not *see* the platform working — everything lived in technical tools. The MVP interface makes the whole process clickable.

**Technology:** React with TypeScript (the industry-standard choice for this kind of dashboard, so it stays easy to hire for and to extend), and TradingView's charting library — the same family of charts traders already recognise. The interface is a static bundle: it can be served by the platform itself (one deployable, nothing new to run) or as its own small container, whichever ops prefers.

**What you can do today**

| Screen | What it shows |
|---|---|
| **Live** | Pick a coin, a candle length and an exchange, and watch a live price chart. Prices update as the exchange publishes them. Side panels show the latest price from each exchange for the same coin, and the raw message the platform publishes — the proof that Binance and Coinbase really do arrive in one identical, dollar-denominated format. |
| **History** | Search the archive by coin and date range, and run the end-of-day archive for a chosen day (sign-in required). |
| **System** | Is data flowing? Candles collected per exchange, live viewers, the live USD conversion rates, and counters for dropped candles and peg fallbacks. |
| **Sign in / profile** | Register, sign in, sign out. Reading data stays public; changing anything requires an account — visible in the interface, where protected actions are disabled with an explanation until you sign in. |

**Deliberately left out of the MVP** — recorded as roadmap item #21: **managing markets from the interface**. Adding, pausing or bulk-adding coins still goes through the API. The platform supports it fully; only the screen is missing. This is the first thing to add if the business wants true self-service.

**Verified end to end.** The interface was run against the real pipeline — live Binance, Kraken and Coinbase data flowing through Kafka and the storage job — with candles appearing on the chart within seconds, the archive and system screens reading real figures, and the error cases (unknown market, empty archive, signed-out actions) all behaving as described. It is covered by automated tests as well (83 interface tests, in addition to the 316 on the platform).

**Honest limitations of this first version**
- ~~The sign-in token is kept in the browser's local storage.~~ **Fixed (September 2026):** sessions now live in a protected cookie the page cannot read — see section 5.
- The chart shows one exchange at a time (roadmap #22).
- No market management screen yet (roadmap #21).

---

## 13. Delivered changes — second round (September 2026)

Four roadmap items plus a full security review.

| # | Business request | Status | What was done | Business effect |
|---|---|---|---|---|
| 6 | **Database migration tooling** | **OK** | Database changes are now applied by a standard tool (Alembic) as a deliberate, versioned step. The platform checks the database is up to date when it starts and **refuses to run against an out-of-date one** rather than failing later in a confusing way. Existing databases catch up with a single command — the manual SQL script and the hand-written `ALTER TABLE` steps are gone. | Schema changes stop being a manual, error-prone job. A release either has the right database or does not start, instead of half-working. |
| 8 | **Nightly archive must be safe to re-run** | **OK** | Re-running a day is now a no-op instead of appending a second copy of it. This closes a real exposure: the platform's automatic retry ran a failed archive up to three times, and the local test setup ran it every ten minutes — each of which was duplicating data. Two further faults found while fixing it: the cleanup step deleted a day's prices on schedule **even when its archive had failed**, and the "re-archive a day" option could delete an archive it had no way to rebuild. Both are fixed. | The archive is trustworthy: the figures cannot be inflated by retries, and a failed run can no longer cost us data. |
| 8b | **Alerting** | **OK** | There were no alerts of any kind in the platform. There are now nine, covering a failed or overdue archive, a stopped price feed, sustained use of the approximate USD rate, and API errors. Delivery to email or Slack is a settings change, not development work. Archive results are also recorded and visible in the API. | We learn about problems ourselves rather than hearing about them from a customer. |
| 11 | **Protect and scale the live stream** | **OK** | Viewers of the same market now share one connection to the data feed instead of each opening their own, so the cost of the live stream depends on how many markets are watched (about 50), not on how many people are watching. Added connection limits, request rate limits, and caps on how much data one request may ask for — the API previously accepted a request for the entire database. | The live stream can serve a large audience on the same hardware, and no single client can overload the platform. |
| 19 | **One error message was in Polish** | **OK** | The "ticker not found" message an integrator sees is now in English, like every other message the API returns. An automated test keeps it that way. | Nothing in the API surface is in a language an international integrator can't read. |
| S | **Security review (OWASP Top 10)** | **OK** | A full review of the whole codebase against the industry-standard OWASP Top 10, with 26 findings — 22 fixed in this round. See [SECURITY_AUDIT.md](SECURITY_AUDIT.md). | An audit-ready document, written to be handed to a customer's security team. |

### What the security review found

The good news first: there is **no SQL injection, no command injection and no unsafe data handling** anywhere in the platform, no password has ever been committed to the code repository, and the browser session design was already better than typical for this stage.

Nearly every finding was one pattern: **a security setting that failed quietly instead of loudly.**

- The **key that signs login sessions** fell back to a value published in our own public code when it wasn't configured. Anyone who read it could have forged a login for any account. Two of our own deployment templates would have hit exactly that. **Fixed:** a production deployment now refuses to start rather than run on it.
- **Session cookies were not required to be HTTPS-only**, so a misconfigured deployment would have sent them in the clear.
- There was **no password policy at all** — `a` was an accepted password for an account that can change what the platform collects and insert prices into it.
- There was **no limit on login attempts**, so passwords could be guessed as fast as a network allows.
- The **container images contained the developer's local configuration file**, which would travel to anyone who could pull the image. (We checked: no real credential is in it today. The practice was the finding.)
- In production, the **monitoring dashboard and the diagnostic trace store were given public internet addresses**, the latter with no password of its own.

All of the above are fixed. Four items are deliberately left open and scheduled, the most important being the **admin role**: today any registered user can change configuration or insert prices, which remains roadmap item #4.

### Also found, not yet fixed — recommended as the next piece of work

The price collector runs **inside** the API, and the production configuration runs **three copies of the API** for reliability. That means three copies of every exchange connection and three copies of every price message: three times the data volume, three times the cost, and a risk of being rate-limited or banned by the exchanges. It is about a day's work to separate them, and it should be done before any production launch.

### Operational notes for this release

- **Database:** run `alembic upgrade head` once against each existing database. It is safe to re-run, and it replaces the previous manual SQL step.
- **Deployment:** apply the new `db-migrate` job on any release carrying a database change; the API waits for it automatically.
- **Configuration:** production deployments must now set a real signing key and `APP_ENV=production`. The platform will not start otherwise — deliberately.
- **Tests:** 429 automated platform tests (up from 329) and 96 interface tests, all passing. Migrations, the archive's re-run safety and the `--replace` refusal were additionally verified against a real PostgreSQL database.

---

## 14. Local currencies, stocks and more crypto (October 2026)

**The request:** the platform showed every price in US dollars only. A user in Poland wants złoty, a user in Norway kroner — automatically, based on where they are — and wants company shares and more coins, not just the original 51 crypto markets.

| Business request | Status | What was done | Business effect |
|---|---|---|---|
| **Prices in the user's own currency** | **OK** | Any price can now be shown in **30 currencies** — euro, złoty, Norwegian/Swedish/Danish krone, Czech koruna, forint, pound, Swiss franc, yen and more. Conversion uses the **European Central Bank's official daily reference rates**, downloaded automatically, and each price is converted at **the rate of its own day**, so last month's chart in złoty uses last month's rate, not today's. | The product speaks the customer's currency. Nobody has to convert dollar prices in their head. |
| **The right currency by default, by country** | **OK** | The web interface looks at where the computer is (its time zone, then its language) and opens in that country's currency: a machine in Poland opens in PLN, in Norway in NOK, in Germany in EUR — even if the browser itself is set to English. A currency picker in the header overrides it; the choice is remembered, and for signed-in users it is saved to their account and follows them to other devices. | "Run it in Poland, get złoty" — with no setting to find. |
| **Company shares** | **OK** | **25 stocks** are collected alongside crypto: 10 US companies (Apple, Microsoft, Nvidia, Amazon, Alphabet, Meta, Tesla, JPMorgan, Visa, AMD), **10 Warsaw Stock Exchange companies** (Orlen, PKO BP, PZU, Pekao, CD Projekt, Allegro, LPP, KGHM, Dino, Santander PL), 3 German (SAP, Siemens, Allianz) and 2 Norwegian (Equinor, DNB). The market picker shows Crypto and Stocks as separate groups. More can be added through the same API as coins. | One platform for crypto and equities; Polish users see Polish blue chips in złoty, at the price the exchange quoted. |
| **More crypto** | **OK** | 51 → **101 crypto markets**: Sui, Toncoin, Pepe, Arbitrum, Optimism, Injective, Filecoin, Internet Computer, Hedera, VeChain, Aave, Render, Algorand, Ethereum Classic, Sei, Celestia, Fetch.ai and others, on the exchanges that list them. | Broader coverage of what customers actually trade. |

### How it works, briefly

Prices are still **stored once, in US dollars**, exactly as before — the storage, the data feed and the archive did not change. Conversion happens at the moment a price is read. This keeps every exchange comparable, means a new currency costs nothing to add, and leaves existing integrations untouched: a client that doesn't ask for a currency still receives dollars.

### Limits worth knowing

- **Stock quotes are delayed about 15 minutes** (stock exchanges license real-time data) and only move during trading hours. The smallest stock candle is 1 minute — there is no 30-second candle for shares.
- **The stock source is Yahoo Finance's free, unofficial interface.** It needs no contract and no key, which made this deliverable possible in days, but it has no service guarantee and may throttle heavy use. Before stock data is **sold**, it should be replaced by a licensed provider; the platform is built so that is a contained change.
- **Reference rates, not trading rates.** One ECB rate per currency per day — right for display and reporting, not for executing trades. The ECB publishes around 16:00 CET on working days; until then, and over weekends, the previous rate is used, and the screen says which date's rate was applied.
- **The collector duplication (section 13) now matters more.** With three copies of the API in production, Yahoo would also be polled three times over, raising the throttling risk. Separating the collector remains the top recommendation.

### Operational notes

- **Database:** run `alembic upgrade head` (adds the rates table, the stock/crypto marker and the saved-currency preference).
- **Storage job:** restart the Flink job once after the first deployment, so it subscribes to the new stock data topics.
- **Network:** the API needs outbound internet access to `www.ecb.europa.eu` and Yahoo Finance.
- **Tests:** 494 automated platform tests (up from 424) and 120 interface tests (up from 96), all passing. The migration, the ECB rate download and PLN conversion were also verified end to end against a real PostgreSQL database.

---

## 15. Names, a market directory, 7 languages and search engines (October 2026)

**The request:** after trying the interface, tickers alone were not enough. "BTC/USD" should read as **Bitcoin, a cryptocurrency**; "AAPL" as **Apple**; users need a place to look up what each instrument is; the interface should speak the visitor's language based on where they are; and the pages should meet search-engine (SEO) standards.

| Business request | Status | What was done | Business effect |
|---|---|---|---|
| **Say what each market is** | **OK** | All 65 instruments behind the 126 default markets have a curated name and classification: crypto by category (digital currency, smart-contract platform, DeFi, meme coin, …), stocks by sector, stock exchange and country. Each market page opens with "Bitcoin (BTC)", its type and a one-line description. Markets added later can be named through the API; until then they show their symbol. | A visitor who doesn't know tickers understands what they are looking at. |
| **A dictionary of markets** | **OK** | A new **Markets** page lists every instrument with name, symbol, type, category or sector, stock exchange and data sources, searchable by name or symbol ("orlen", "AAPL") and filterable by crypto/stocks. | One place to discover and look up everything the platform tracks. |
| **Translated by location** | **OK** | The whole interface is available in **English, Polish, German, French, Norwegian, Italian and Spanish**. A visitor's first page opens in their language — from their browser language, or, on an English browser, from the country their computer is in (a machine in Poland gets Polish). A picker switches language and remembers the choice. Company and coin names are never translated; categories, sectors and descriptions are. Numbers and currencies are formatted the local way ("65 200,00 zł"). | Local users get a local product, consistent with the local-currency work in section 14. |
| **SEO** | **OK** | Every market and every language has its own address (`/pl/markets/bitcoin-btc`). Each page is delivered with its own title, description, language tags linking the 7 versions to each other, link-preview data for social networks, and structured data search engines understand (for stocks, the official ticker such as `WSE:PKN`). A sitemap lists all 476 pages; private pages (login, account) are kept out of search results; missing pages return a proper "not found". | The platform can be found in search in seven languages, and shared links show a proper title and description. |

### Limits worth knowing

- **Translations are first drafts.** They were written by the engineering team, not by native speakers. Before marketing in a country, have a native speaker review that language (about one hour per language — the text is in one file each).
- **Search ranking takes time.** The pages are now indexable; ranking depends on content, links and time. Set the public site address (`SITE_URL`) in production so the links search engines see are correct.

### Operational notes

- **Database:** run `alembic upgrade head` (adds the instruments table; names are filled in automatically on startup).
- **Configuration:** set `SITE_URL` to the public address in production.
- **Tests:** 573 automated platform tests and 200 interface tests, all passing; also verified end to end against a real PostgreSQL database (page titles, language tags, 404s, sitemap).
