"""
Startup guard: the database schema must be at the migrations' head revision.

Before Alembic, app/main.py called Base.metadata.create_all on every boot. That
created missing tables but never altered existing ones, so a column added to a
model simply never appeared on a deployed database and the mismatch only
surfaced later as a query error. Worse, in production three API replicas each
ran it concurrently.

Migrations now own the schema, and the API only *verifies* it. Applying them is
a separate, deliberate step (`alembic upgrade head`, or the db-migrate Job in
Kubernetes) so that exactly one process performs DDL.

Also runnable as a command, which is what the API pods' initContainer uses:

    python -m app.models.schema_check           # check once, exit 0 or 1
    python -m app.models.schema_check --wait    # block until the DB is at head
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import DB_SCHEMA_CHECK
from app.models.database import engine as default_engine

logger = logging.getLogger(__name__)

# app/models/schema_check.py → repo root (and /app inside the image, which is
# why the Dockerfile has to COPY alembic.ini and migrations/).
REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "migrations"

UPGRADE_COMMAND = "alembic upgrade head"


class SchemaOutOfDateError(RuntimeError):
    """The database is not at the migrations' head revision."""


def _script_directory() -> ScriptDirectory:
    config = Config(str(ALEMBIC_INI))
    # Resolve script_location absolutely: alembic.ini's relative path only works
    # when the process happens to be started from the repo root.
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(config)


def head_revisions() -> tuple[str, ...]:
    """The head revision(s) on disk. More than one means the history has branched."""
    return tuple(_script_directory().get_heads())


async def current_revision(engine: AsyncEngine | None = None) -> str | None:
    """The revision the database reports, or None if it has never been migrated."""
    engine = engine or default_engine
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision()
        )


async def assert_schema_at_head(engine: AsyncEngine | None = None) -> None:
    """
    Raise unless the database is at head. A no-op when DB_SCHEMA_CHECK is off,
    which is how throwaway dev databases and the test suite opt out.
    """
    if not DB_SCHEMA_CHECK:
        logger.warning("DB_SCHEMA_CHECK is off — not verifying the database schema")
        return

    heads = head_revisions()
    if len(heads) > 1:
        raise SchemaOutOfDateError(
            f"The migration history has branched into {len(heads)} heads ({', '.join(heads)}). "
            "Merge them with `alembic merge` before starting the application."
        )

    head = heads[0]
    current = await current_revision(engine)

    if current is None:
        raise SchemaOutOfDateError(
            "The database has no Alembic version stamp — it has never been migrated. "
            f"Run `{UPGRADE_COMMAND}` against it first. "
            "(A database built by the old create_all startup path is handled: the "
            "baseline revision detects existing tables and skips them.)"
        )
    if current != head:
        raise SchemaOutOfDateError(
            f"The database is at revision {current}, but the application expects {head}. "
            f"Run `{UPGRADE_COMMAND}`."
        )

    logger.info(f"Database schema verified at revision {head}")


async def _wait_for_head(timeout: float, interval: float) -> int:
    """Poll until the database reaches head. Used by the API pods' initContainer."""
    deadline = asyncio.get_running_loop().time() + timeout
    last_error: Exception | None = None

    while asyncio.get_running_loop().time() < deadline:
        try:
            await assert_schema_at_head()
            return 0
        except Exception as error:          # not migrated yet, or DB not up yet
            last_error = error
            logger.info(f"Waiting for the database to reach head: {error}")
            await asyncio.sleep(interval)

    logger.error(f"Timed out after {timeout:.0f}s waiting for the schema: {last_error}")
    return 1


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the database is at the migrations' head.")
    parser.add_argument("--wait", action="store_true", help="block until the database reaches head")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds to wait with --wait")
    parser.add_argument("--interval", type=float, default=3.0, help="seconds between polls")
    args = parser.parse_args(argv)

    if args.wait:
        return await _wait_for_head(args.timeout, args.interval)

    try:
        await assert_schema_at_head()
    except Exception as error:
        logger.error(str(error))
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        sys.exit(asyncio.run(_main()))
    finally:
        pass
