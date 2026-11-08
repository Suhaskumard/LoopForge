"""Cross-process run leases (ADR-0014): at most one process drives a task at a time.

A lease is a row keyed by task id. It is acquired with a conditional UPDATE (takeover only when
expired or already ours) or an INSERT that the primary key serialises, so it is correct on both
SQLite and Postgres without advisory locks. A heartbeat thread keeps it alive; if the owner dies
the lease expires and another process may resume the task from its checkpoint.
"""

import logging
import os
import socket
import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.models import RunLease
from app.utils.logging import thread_target
from app.utils.metrics import LEASE_TAKEOVERS

log = logging.getLogger("loopforge.lease")

# One identity per process, so a restarted process never mistakes itself for its dead predecessor.
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ttl(ttl: float | None) -> timedelta:
    return timedelta(seconds=settings.lease_ttl_seconds if ttl is None else ttl)


def acquire(
    db: Session, task_id: uuid.UUID, owner: str = OWNER_ID, ttl: float | None = None
) -> bool:
    now = _now()
    expires = now + _ttl(ttl)
    previous = db.get(RunLease, task_id)
    previous_owner = previous.owner if previous is not None else None
    db.expire_all()
    taken = db.execute(
        update(RunLease)
        .where(RunLease.task_id == task_id, or_(RunLease.owner == owner, RunLease.expires_at < now))
        .values(owner=owner, expires_at=expires, acquired_at=now)
    )
    if taken.rowcount == 1:
        db.commit()
        if previous_owner is not None and previous_owner != owner:
            LEASE_TAKEOVERS.inc()
            log.warning(
                "lease takeover: task %s from %s to %s (the previous owner stopped renewing)",
                task_id, previous_owner, owner,
            )  # fmt: skip
        return True
    try:
        db.add(RunLease(task_id=task_id, owner=owner, expires_at=expires, acquired_at=now))
        db.commit()
        return True
    except IntegrityError:  # someone else holds a live lease
        db.rollback()
        return False


def renew(db: Session, task_id: uuid.UUID, owner: str = OWNER_ID, ttl: float | None = None) -> bool:
    res = db.execute(
        update(RunLease)
        .where(RunLease.task_id == task_id, RunLease.owner == owner)
        .values(expires_at=_now() + _ttl(ttl))
    )
    db.commit()
    return res.rowcount == 1


def release(db: Session, task_id: uuid.UUID, owner: str = OWNER_ID) -> None:
    db.execute(delete(RunLease).where(RunLease.task_id == task_id, RunLease.owner == owner))
    db.commit()


def is_held(db: Session, task_id: uuid.UUID) -> bool:
    db.expire_all()
    lease = db.get(RunLease, task_id)
    return lease is not None and lease.expires_at >= _now()


class Heartbeat:
    """Renews a lease from a daemon thread (own session) until stopped."""

    def __init__(self, factory: sessionmaker[Session], task_id: uuid.UUID, owner: str = OWNER_ID):
        self._factory, self._task_id, self._owner = factory, task_id, owner
        self._stop = threading.Event()
        self.lost = False
        self._thread = threading.Thread(target=thread_target(self._run), daemon=True)

    def _run(self) -> None:
        interval = max(settings.lease_ttl_seconds / 3, 0.05)
        while not self._stop.wait(interval):
            try:
                with self._factory() as db:
                    if not renew(db, self._task_id, self._owner):
                        self.lost = True
                        log.error("lease for task %s was lost", self._task_id)
                        return
            except Exception:
                log.exception("lease heartbeat failed for task %s", self._task_id)

    def __enter__(self) -> "Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
