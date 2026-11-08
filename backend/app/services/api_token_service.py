"""Scoped API tokens for automation (Phase 11, ADR-0018). Only the SHA-256 of a token is stored."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ApiToken

PREFIX = "lfk_"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_api_token(value: str) -> bool:
    return value.startswith(PREFIX)


def create(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    scope: str,
    expires_days: int | None,
) -> tuple[ApiToken, str]:
    """Returns the row and the plaintext token, which is never retrievable again."""
    secret = PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        org_id=org_id,
        user_id=user_id,
        name=name,
        prefix=secret[:8],
        token_hash=hash_token(secret),
        scope=scope,
        expires_at=_now() + timedelta(days=expires_days) if expires_days else None,
    )
    db.add(row)
    db.commit()
    return row, secret


def authenticate(db: Session, token: str) -> ApiToken | None:
    row = db.scalars(select(ApiToken).where(ApiToken.token_hash == hash_token(token))).first()
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= _now():
        return None
    row.last_used_at = _now()
    db.commit()
    return row


def list_tokens(db: Session, org_id: uuid.UUID) -> list[ApiToken]:
    return list(
        db.scalars(select(ApiToken).where(ApiToken.org_id == org_id).order_by(ApiToken.created_at))
    )


def revoke(db: Session, org_id: uuid.UUID, token_id: uuid.UUID) -> ApiToken | None:
    row = db.get(ApiToken, token_id)
    if row is None or row.org_id != org_id:
        return None
    if row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()
    return row
