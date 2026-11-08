"""Organizations and memberships (Phase 10, ADR-0017).

Roles are ordered viewer < developer < approver < admin and are always read from the database, never
from the JWT, so a role change or removal takes effect on the very next request.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import ROLES, Membership, Organization, User

ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}


@dataclass(frozen=True)
class OrgContext:
    org_id: uuid.UUID
    role: str

    def allows(self, minimum: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum]


def _slug(base: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{cleaned[:30] or 'org'}-{uuid.uuid4().hex[:8]}"


def create_org(db: Session, name: str, admin: User) -> Organization:
    org = Organization(name=name, slug=_slug(name))
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=admin.id, role="admin"))
    db.commit()
    return org


def create_personal_org(db: Session, user: User) -> Organization:
    return create_org(db, f"{user.email.split('@')[0]}'s workspace", user)


def memberships_of(db: Session, user_id: uuid.UUID) -> list[Membership]:
    return list(
        db.scalars(
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at, Membership.id)
        )
    )


def resolve(db: Session, user_id: uuid.UUID, requested: uuid.UUID | None) -> OrgContext | None:
    """Active org + role. `requested` must be an org the user belongs to; None = their first."""
    stmt = select(Membership).where(Membership.user_id == user_id)
    if requested is not None:
        stmt = stmt.where(Membership.org_id == requested)
    else:
        stmt = stmt.order_by(Membership.created_at, Membership.id)
    member = db.scalars(stmt).first()
    return None if member is None else OrgContext(member.org_id, member.role)


def count_admins(db: Session, org_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == "admin")
        )
        or 0
    )
