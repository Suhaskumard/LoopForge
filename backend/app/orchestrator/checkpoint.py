"""Persistent LangGraph checkpointer (spec §5.1 / Phase 4 "resumable workflows").

State is saved after every node, so a process that dies mid-iteration can resume from the last
completed node. SQLite databases get a sibling `<db>.checkpoints.sqlite` file; PostgreSQL uses
langgraph's PostgresSaver on the same database. `:memory:` falls back to an in-process saver
(not durable, development only).
"""

import logging
import sqlite3
import threading
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.engine import URL

_lock = threading.Lock()
_cache: dict[str, BaseCheckpointSaver[Any]] = {}
_closers: list[Any] = []

log = logging.getLogger("loopforge.checkpoint")


def _sqlite_saver(path: str) -> BaseCheckpointSaver[Any]:
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(path, check_same_thread=False)
    _closers.append(conn)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _postgres_saver(url: URL) -> BaseCheckpointSaver[Any]:
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row

    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    _closers.append(conn)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver


def get_checkpointer(url: URL) -> BaseCheckpointSaver[Any]:
    key = url.render_as_string(hide_password=True)
    with _lock:
        if key in _cache:
            return _cache[key]
        backend = url.get_backend_name()
        saver: BaseCheckpointSaver[Any]
        if backend == "sqlite":
            if not url.database or url.database == ":memory:":
                saver = MemorySaver()
            else:
                saver = _sqlite_saver(f"{url.database}.checkpoints.sqlite")
        elif backend == "postgresql":
            saver = _postgres_saver(url)
        else:
            saver = MemorySaver()
        _cache[key] = saver
        return saver


def close_checkpointers() -> None:
    """Release connections (tests / shutdown)."""
    with _lock:
        for c in _closers:
            try:
                c.close()
            except Exception:  # already closed: nothing to do at shutdown
                log.debug("checkpointer was already closed")
        _closers.clear()
        _cache.clear()
