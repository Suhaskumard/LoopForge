"""Single-use, hashed, expiring tokens for email verification and password reset (Phase 15)."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import EmailToken, User


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(db: Session, user: User, purpose: str) -> str:
    """Create a token (older unused ones of the same purpose die) and return the raw value."""
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=_now())
    )
    ttl = (
        timedelta(hours=settings.verify_token_ttl_hours)
        if purpose == "verify"
        else timedelta(minutes=settings.reset_token_ttl_minutes)
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        EmailToken(
            id=uuid.uuid4(), user_id=user.id, purpose=purpose, token_hash=_hash(raw),
            expires_at=_now() + ttl,
        )
    )  # fmt: skip
    db.commit()
    return raw


def consume(db: Session, raw: str, purpose: str) -> User | None:
    """Mark the token used and return its user; None if unknown, wrong purpose, used or expired."""
    row = db.scalars(
        select(EmailToken).where(EmailToken.token_hash == _hash(raw), EmailToken.purpose == purpose)
    ).first()
    if row is None or row.used_at is not None or row.expires_at <= _now():
        return None
    row.used_at = _now()
    user = db.get(User, row.user_id)
    db.commit()
    return user
