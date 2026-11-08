"""Emailed organization invitations (Phase 15). Tokens are single-use and stored hashed."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Membership, OrgInvite, User


class InviteError(Exception):
    """The invitation cannot be accepted (the message is safe to show)."""


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create(
    db: Session, org_id: uuid.UUID, email: str, role: str, invited_by: uuid.UUID
) -> tuple[OrgInvite, str]:
    """A new invitation; an older pending one for the same address is revoked first."""
    email = email.lower()
    for old in db.scalars(
        select(OrgInvite).where(
            OrgInvite.org_id == org_id,
            OrgInvite.email == email,
            OrgInvite.accepted_at.is_(None),
            OrgInvite.revoked_at.is_(None),
        )
    ):
        old.revoked_at = _now()
    raw = secrets.token_urlsafe(32)
    invite = OrgInvite(
        org_id=org_id, email=email, role=role, token_hash=_hash(raw), invited_by=invited_by,
        expires_at=_now() + timedelta(days=settings.invite_ttl_days),
    )  # fmt: skip
    db.add(invite)
    db.commit()
    return invite, raw


def pending(db: Session, org_id: uuid.UUID) -> list[OrgInvite]:
    return list(
        db.scalars(
            select(OrgInvite)
            .where(
                OrgInvite.org_id == org_id,
                OrgInvite.accepted_at.is_(None),
                OrgInvite.revoked_at.is_(None),
                OrgInvite.expires_at > _now(),
            )
            .order_by(OrgInvite.created_at.desc())
        )
    )


def revoke(db: Session, org_id: uuid.UUID, invite_id: uuid.UUID) -> bool:
    inv = db.get(OrgInvite, invite_id)
    if inv is None or inv.org_id != org_id or inv.accepted_at or inv.revoked_at:
        return False
    inv.revoked_at = _now()
    db.commit()
    return True


def accept(db: Session, user: User, raw: str) -> OrgInvite:
    inv = db.scalars(select(OrgInvite).where(OrgInvite.token_hash == _hash(raw))).first()
    if inv is None or inv.accepted_at or inv.revoked_at or inv.expires_at <= _now():
        raise InviteError("This invitation is invalid or has expired")
    if user.email.lower() != inv.email:
        raise InviteError("This invitation was sent to a different email address")
    if user.email_verified_at is None:
        raise InviteError("Verify your email address before accepting an invitation")
    exists = db.scalars(
        select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == user.id)
    ).first()
    if exists is None:
        db.add(Membership(org_id=inv.org_id, user_id=user.id, role=inv.role))
    inv.accepted_at = _now()
    db.commit()
    return inv
