"""
Guards on the migration history and the startup schema check.

These run without a database. The end-to-end migration behaviour (a real
upgrade against PostgreSQL, and model-vs-migration drift) lives in
tests/integration/test_migrations.py, which needs TEST_POSTGRES_URL.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models import schema_check
from app.models.schema_check import SchemaOutOfDateError, assert_schema_at_head, head_revisions


def test_migration_history_has_exactly_one_head():
    """
    Two heads mean someone branched the history — `alembic upgrade head` then
    fails and a deploy is stuck. Cheaper to catch here than in a release.
    """
    heads = head_revisions()
    assert len(heads) == 1, f"migration history has branched: {heads}"


def test_baseline_is_reachable_from_head():
    from alembic.script import ScriptDirectory

    script = schema_check._script_directory()
    assert isinstance(script, ScriptDirectory)
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert "0001_baseline" in revisions
    assert "0002_legacy_alignment" in revisions


@pytest.fixture
def schema_check_enabled():
    """
    conftest sets DB_SCHEMA_CHECK=false for the whole suite (the SQLite schema
    comes from create_all), so these tests have to switch the guard back on.
    """
    with patch.object(schema_check, "DB_SCHEMA_CHECK", True):
        yield


async def test_assert_schema_at_head_passes_when_revision_matches(schema_check_enabled):
    head = head_revisions()[0]
    with patch.object(schema_check, "current_revision", AsyncMock(return_value=head)):
        await assert_schema_at_head()      # must not raise


async def test_assert_schema_at_head_rejects_an_unmigrated_database(schema_check_enabled):
    with patch.object(schema_check, "current_revision", AsyncMock(return_value=None)):
        with pytest.raises(SchemaOutOfDateError, match="never been migrated"):
            await assert_schema_at_head()


async def test_assert_schema_at_head_rejects_a_stale_database(schema_check_enabled):
    with patch.object(schema_check, "current_revision", AsyncMock(return_value="0001_baseline")):
        with pytest.raises(SchemaOutOfDateError, match="alembic upgrade head"):
            await assert_schema_at_head()


async def test_assert_schema_at_head_is_skipped_when_disabled():
    """DB_SCHEMA_CHECK=false is how the test suite and throwaway dev DBs opt out."""
    probe = AsyncMock(return_value=None)
    with patch.object(schema_check, "DB_SCHEMA_CHECK", False), \
         patch.object(schema_check, "current_revision", probe):
        await assert_schema_at_head()      # must not raise
    probe.assert_not_awaited()             # and must not even touch the database
