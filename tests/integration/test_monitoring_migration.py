"""The monitoring revision is reversible and preserves existing user data."""
import importlib.util
import uuid
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base, User


def test_monitoring_revision_matches_models_and_preserves_users(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'monitoring-migration.db'}")
    legacy = [table for table in Base.metadata.sorted_tables if not table.name.startswith('monitoring_')]
    Base.metadata.create_all(engine, tables=legacy)
    user_id = uuid.uuid4()
    with Session(engine) as db:
        db.add(User(id=user_id, email='keep@example.com', hashed_password='unchanged', is_active=True))
        db.commit()
    path = Path(__file__).resolve().parents[2] / 'migrations/versions/2026_10_31_1200-0008_monitoring.py'
    spec = importlib.util.spec_from_file_location('monitoring_revision', path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision.upgrade()
        assert compare_metadata(context, Base.metadata) == []
        with Operations.context(context):
            revision.downgrade()
        assert not any(name.startswith('monitoring_') for name in inspect(connection).get_table_names())
        with Operations.context(context):
            revision.upgrade()
        assert compare_metadata(context, Base.metadata) == []
    with Session(engine) as db:
        assert db.get(User, user_id).email == 'keep@example.com'
    engine.dispose()
