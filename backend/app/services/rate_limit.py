"""Fixed-window rate limiting shared by every API process (Phase 18, docs/api_policy.md).

One counter row per (key, window). The increment is an UPDATE that falls back to an INSERT, and
retries the UPDATE if two processes race on the insert, so no request is lost or double-counted.
Fixed windows allow a burst of up to 2x the limit across a window boundary; that is the accepted
trade-off against a log-based
sliding window (one row per request). Old windows are purged by ``purge``.
"""

import time
from dataclasses import dataclass

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import RateCounter

WINDOW_SECONDS = 60


@dataclass(frozen=True)
class RateStatus:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int  # until the window ends

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_seconds),
        }


def hit(db: Session, key: str, limit: int, now: float | None = None) -> RateStatus:
    """Count one request against `key`. `limit` <= 0 means unlimited (nothing is stored)."""
    t = time.time() if now is None else now
    window = int(t // WINDOW_SECONDS) * WINDOW_SECONDS
    reset = int(window + WINDOW_SECONDS - t) + 1
    if limit <= 0:
        return RateStatus(True, 0, 0, reset)
    count = _increment(db, key, window)
    return RateStatus(count <= limit, limit, max(0, limit - count), reset)


def _increment(db: Session, key: str, window: int) -> int:
    for _ in range(3):
        row = db.execute(
            update(RateCounter)
            .where(RateCounter.key == key, RateCounter.window_start == window)
            .values(count=RateCounter.count + 1)
            .returning(RateCounter.count)  # atomic: the value THIS request produced
        ).first()
        if row is not None:
            db.commit()
            return int(row[0])
        try:
            db.add(RateCounter(key=key, window_start=window, count=1))
            db.commit()
            return 1
        except IntegrityError:  # another process created the row first: increment it instead
            db.rollback()
    raise RuntimeError("rate counter could not be updated")  # pragma: no cover


def purge(db: Session, older_than_seconds: int = 3600, now: float | None = None) -> int:
    cutoff = int((time.time() if now is None else now) - older_than_seconds)
    res = db.execute(delete(RateCounter).where(RateCounter.window_start < cutoff))
    db.commit()
    return int(res.rowcount or 0)
