# Repository Guidelines

## Project Structure & Module Organization

- `app/` contains the application package. `main.py` defines the FastAPI app and lifecycle; `routers/` exposes HTTP/WebSocket endpoints; `models/` contains SQLAlchemy ORM models; `schemas/` contains Pydantic request/response schemas; `helpers/` contains reusable application helpers; `kafka/` handles exchange-to-Kafka streaming; and `flink_jobs/` contains the Kafka-to-TimescaleDB pipeline.
- `tests/` contains asynchronous API/integration tests and unit tests (`tests/unit/`). Shared fixtures are in `tests/conftest.py`.
- `requirements.txt` lists Python dependencies. `trading_master.db` is local development data; do not commit credentials or production data.

## Build, Test, and Development Commands

Use the project virtual environment when available:

```bash
source .env/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

`pytest` runs all tests according to `pytest.ini` (including asyncio support). Run a focused suite with `pytest tests/unit` or a single test with `pytest tests/test_market.py -k candles`. The Uvicorn command starts the API on the default local port. Kafka and PostgreSQL/TimescaleDB must be configured through environment variables before exercising live streaming or persistence.

## Coding Style & Naming Conventions

Follow standard Python style: four-space indentation, `snake_case` for functions, variables, and modules, `PascalCase` for classes, and uppercase names for configuration constants. Keep type hints on public functions and preserve the existing async style for I/O. Format imports and code consistently with the surrounding files; no formatter or linter is currently configured.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio`. Name files `test_*.py`, test functions `test_*`, and test classes `Test*`. Mock Kafka and exchange clients in unit tests; use fixtures for database/API behavior. Add regression coverage for new endpoints, validation rules, and stream transformations.

## Commit & Pull Request Guidelines

This repository has no commits yet, so no established message pattern is available. Use concise imperative messages such as `Add candle interval validation`, preferably grouped by one logical change. Pull requests should explain the behavior change, list validation commands (for example, `pytest`), identify required environment or infrastructure changes, and include API examples or screenshots when the interface changes.

## Security & Configuration Tips

Keep `.env` files, exchange API keys, database passwords, and Kafka credentials local. Public market streams do not require exchange keys. Review configuration defaults before running against shared infrastructure, and never include secrets or generated database files in patches.
