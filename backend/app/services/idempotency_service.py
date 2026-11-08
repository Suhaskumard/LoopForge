"""Idempotency keys for safe retries of POST requests (Phase 18, docs/api_policy.md).

A client sends ``Idempotency-Key: <opaque string>`` on a create. The first request with a key runs
normally and its 2xx response is stored; a retry with the same key and the same body gets that exact
response back (header ``Idempotent-Replay: true``) without running again. The same key with a
different
body is a client bug -> 422. A retry that arrives while the first is still running -> 409. A failed
(non-2xx) first attempt is forgotten, so the retry runs for real.

The key is scoped by a hash of the caller's credential and organization, so one caller can neither
replay nor probe another's keys. Concurrency: the unique constraint admits exactly one winner.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import IdempotencyKey

MAX_STORED_BODY = 256 * 1024
KEY_MAX_LENGTH = 200


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def request_hash(method: str, path: str, body: bytes) -> str:
    return hashlib.sha256(method.encode() + b"\0" + path.encode() + b"\0" + body).hexdigest()


def scope_of(credential: str, org: str | None) -> str:
    return hashlib.sha256(f"{credential}|{org or ''}".encode()).hexdigest()


@dataclass(frozen=True)
class Begin:
    outcome: str  # "run" | "replay" | "mismatch" | "in_progress"
    record_id: uuid.UUID | None = None
    status_code: int = 0
    body: str = ""
    headers: dict[str, Any] | None = None


def begin(db: Session, scope: str, key: str, route: str, req_hash: str) -> Begin:
    row = IdempotencyKey(scope=scope, key=key, route=route, request_hash=req_hash)
    db.add(row)
    try:
        db.commit()
        return Begin("run", row.id)
    except IntegrityError:
        db.rollback()
    existing = db.scalars(
        select(IdempotencyKey).where(
            IdempotencyKey.scope == scope, IdempotencyKey.key == key, IdempotencyKey.route == route
        )
    ).first()
    if existing is None:  # deleted between the insert and the read: just run
        return begin(db, scope, key, route, req_hash)
    if existing.request_hash != req_hash:
        return Begin("mismatch")
    if existing.state != "done":
        return Begin("in_progress")
    return Begin(
        "replay",
        existing.id,
        existing.status_code or 200,
        existing.response_body or "",
        dict(existing.response_headers or {}),
    )


def complete(
    db: Session, record_id: uuid.UUID, status_code: int, body: str, headers: dict[str, str]
) -> None:
    row = db.get(IdempotencyKey, record_id)
    if row is None:  # purged meanwhile
        return
    row.state, row.status_code, row.response_body = "done", status_code, body
    row.response_headers = headers
    db.commit()


def forget(db: Session, record_id: uuid.UUID) -> None:
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.id == record_id))
    db.commit()


def purge(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or _now()) - timedelta(hours=settings.idempotency_ttl_hours)
    res = db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
    db.commit()
    return int(res.rowcount or 0)
