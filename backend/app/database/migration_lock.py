"""Serialise schema migrations across processes (Phase 12, ADR-0019).

Several replicas (or a deploy script and a replica) starting at once used to race on
`alembic upgrade head`. On PostgreSQL a session-level advisory lock makes the second runner wait
until the first has finished, then find nothing left to do. SQLite is single-writer and
file-local, so the lock is a no-op there.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text

# Arbitrary constant shared by every LoopForge migration runner ("LFmigrate" as a 64-bit int).
MIGRATION_LOCK_KEY = 0x4C466D6967726174


@contextmanager
def migration_lock(connection: Any, key: int = MIGRATION_LOCK_KEY) -> Iterator[None]:
    if connection.dialect.name != "postgresql":
        yield
        return
    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
    try:
        yield
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        connection.commit()
