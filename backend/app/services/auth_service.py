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


def _issue(
    db: Session,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    user_agent: str = "",
    ip: str = "",
    created_at: datetime | None = None,
) -> str:
    raw = new_refresh_token()
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_refresh_token(raw),
        expires_at=_now() + timedelta(days=settings.refresh_expire_days),
        user_agent=user_agent[:300],
        ip=ip[:64],
        last_used_at=_now(),
    )
    if created_at is not None:
        row.created_at = created_at  # a rotation keeps the session's original start time
    db.add(row)
    db.commit()
    return raw


def start_session(db: Session, user: User, user_agent: str = "", ip: str = "") -> str:
    """Begin a new rotation family and return the first refresh token."""
    return _issue(db, user.id, uuid.uuid4(), user_agent, ip)


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
    if user is None or not user.active:
        raise InvalidRefreshToken
    row.revoked_at = _now()
    db.commit()
    return user, _issue(
        db, row.user_id, row.family_id, row.user_agent, row.ip, created_at=row.created_at
    )


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


# ---- session management (Phase 15) ---------------------------------------------------------


def list_sessions(db: Session, user: User) -> list[RefreshToken]:
    """The newest live token of each session family (one row per signed-in device)."""
    rows = db.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > _now(),
        )
        .order_by(RefreshToken.created_at.desc())
    ).all()
    seen: set[uuid.UUID] = set()
    out = []
    for r in rows:
        if r.family_id not in seen:
            seen.add(r.family_id)
            out.append(r)
    return out


def family_of(db: Session, raw_token: str) -> uuid.UUID | None:
    row = db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    ).first()
    return row.family_id if row else None


def revoke_session(db: Session, user: User, family_id: uuid.UUID) -> bool:
    """Revoke one of the user's own sessions. False if it is not theirs / not live."""
    owned = db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).first()
    if owned is None:
        return False
    _revoke_family(db, family_id)
    return True
