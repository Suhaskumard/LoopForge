import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import LoginAttempt, RefreshToken, User
from app.utils.security import hash_refresh_token, new_refresh_token


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class InvalidRefreshToken(Exception):
    pass


class RefreshTokenReuse(InvalidRefreshToken):
    """A spent refresh token was presented again: a theft signal (the whole family was revoked)."""

    def __init__(self, user_id: uuid.UUID) -> None:
        super().__init__("refresh token reuse")
        self.user_id = user_id


# ---- login rate limiting (DB-backed so it is shared across workers) ----------------------


def is_login_blocked(db: Session, key: str) -> bool:
    since = _now() - timedelta(seconds=settings.login_window_seconds)
    count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.key == key, LoginAttempt.created_at > since)
    )
    return (count or 0) >= settings.login_max_attempts


def record_login_failure(db: Session, key: str) -> None:
    db.add(LoginAttempt(key=key))
    db.commit()


def clear_login_failures(db: Session, key: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
    db.commit()


# ---- refresh tokens ------------------------------------------------------------------------


def _issue(db: Session, user_id: uuid.UUID, family_id: uuid.UUID) -> str:
    raw = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_refresh_token(raw),
            expires_at=_now() + timedelta(days=settings.refresh_expire_days),
        )
    )
    db.commit()
    return raw


def start_session(db: Session, user: User) -> str:
    """Begin a new rotation family and return the first refresh token."""
    return _issue(db, user.id, uuid.uuid4())


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()


def rotate(db: Session, raw_token: str) -> tuple[User, str]:
    """Exchange a refresh token for a new one. Reuse of a spent token revokes the whole family."""
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    ).first()
    if row is None:
        raise InvalidRefreshToken
    if row.revoked_at is not None:
        _revoke_family(db, row.family_id)  # theft signal: kill every token in the chain
        raise RefreshTokenReuse(row.user_id)
    if row.expires_at <= _now():
        raise InvalidRefreshToken
    user = db.get(User, row.user_id)
    if user is None:
        raise InvalidRefreshToken
    row.revoked_at = _now()
    db.commit()
    return user, _issue(db, row.user_id, row.family_id)


def revoke(db: Session, raw_token: str) -> None:
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    ).first()
    if row is not None:
        _revoke_family(db, row.family_id)


def revoke_all(db: Session, user: User) -> None:
    """Global logout: bump token_version (kills access tokens) and revoke all refresh tokens."""
    user.token_version += 1
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()
