"""
Insert-ignore-duplicates, for both PostgreSQL and SQLite.

SQLAlchemy 2.0 has no dialect-neutral upsert: `ON CONFLICT` is spelled in the
dialect-specific insert() construct. Deployments run PostgreSQL and the test
suite runs SQLite, so both are needed — the alternative, a SELECT-then-INSERT,
has a race between the two statements and costs a round trip per batch.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession


class UnsupportedDialectError(RuntimeError):
    """The database has no ON CONFLICT support this helper knows about."""


async def insert_ignore_duplicates(
    session: AsyncSession,
    table: Any,
    rows: Sequence[dict] | Iterable[dict],
    index_elements: Sequence[str],
) -> int:
    """
    Insert `rows`, silently skipping any that collide on `index_elements`.

    Returns the number of rows actually inserted, so a caller can report how
    many were new versus already present. Does not commit — the caller controls
    the transaction boundary.

    The count comes from RETURNING, not rowcount: PostgreSQL reports rowcount
    -1 for an executemany INSERT, so a rowcount-based tally silently read as
    "nothing inserted" on exactly the database that runs in production.

    `table` is a mapped class or a Table. `index_elements` must match a unique
    constraint or index, otherwise PostgreSQL raises rather than ignoring.
    """
    rows = list(rows)
    if not rows:
        return 0

    target = table.__table__ if hasattr(table, "__table__") else table
    dialect = session.bind.dialect.name if session.bind is not None else ""

    if dialect == "postgresql":
        statement = postgresql.insert(target)
    elif dialect == "sqlite":
        statement = sqlite.insert(target)
    else:
        raise UnsupportedDialectError(
            f"insert_ignore_duplicates has no ON CONFLICT support for dialect {dialect!r}"
        )

    primary_key = list(target.primary_key.columns)[0]
    statement = (
        statement
        .on_conflict_do_nothing(index_elements=list(index_elements))
        .returning(primary_key)
    )

    # Counted with RETURNING rather than rowcount: on PostgreSQL an executemany
    # INSERT reports rowcount -1 regardless of how many rows it wrote, so the
    # caller would have been told nothing was inserted. RETURNING yields exactly
    # one row per row actually written, and none for a skipped conflict.
    result = await session.execute(statement, rows)
    return len(result.fetchall())
