"""Organizations, members, usage, audit log, export and data lifecycle (Phase 10, ADR-0017)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_current_user, require_org_role
from app.database.models import AuditLog, Membership, Organization, User
from app.database.session import get_db
from app.schemas.org import (
    AuditOut,
    DeleteDataOut,
    DeleteDataRequest,
    MemberAdd,
    MemberOut,
    MemberUpdate,
    OrgCreate,
    OrgMembershipOut,
    OrgOut,
    OrgUpdate,
    RetentionOut,
    UsageOut,
)
from app.services import audit_service, org_service, quota_service, retention_service

router = APIRouter(prefix="/orgs", tags=["organizations"])

viewer = require_org_role("viewer")
admin = require_org_role("admin")


def _org(db: Session, p: Principal) -> Organization:
    org = db.get(Organization, p.org_id)
    assert org is not None
    return org


@router.get("", response_model=list[OrgMembershipOut])
def my_orgs(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[OrgMembershipOut]:
    out = []
    for m in org_service.memberships_of(db, user.id):
        org = db.get(Organization, m.org_id)
        assert org is not None
        out.append(OrgMembershipOut(id=org.id, name=org.name, slug=org.slug, role=m.role))
    return out


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
def create(
    data: OrgCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    org = org_service.create_org(db, data.name, user)
    audit_service.record(
        db, org_id=org.id, actor_id=user.id, action="org.create", target_type="org",
        target_id=org.id, detail={"name": org.name}, request=request,
    )  # fmt: skip
    return org


@router.get("/{org_id}", response_model=OrgOut)
def get_org(p: Principal = Depends(viewer), db: Session = Depends(get_db)) -> Organization:
    return _org(db, p)


@router.patch("/{org_id}", response_model=OrgOut)
def update(
    data: OrgUpdate,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> Organization:
    org = _org(db, p)
    changes = data.model_dump(exclude_unset=True)
    for required in ("name", "redact_pii"):
        if required in changes and changes[required] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{required} cannot be cleared"
            )
    before = {k: getattr(org, k) for k in changes}
    for key, value in changes.items():
        setattr(org, key, value)
    db.commit()
    audit_service.record(
        db, org_id=org.id, actor_id=p.user.id, action="org.update", target_type="org",
        target_id=org.id, detail={"before": before, "after": changes}, request=request,
    )  # fmt: skip
    return org


@router.get("/{org_id}/usage", response_model=UsageOut)
def usage(p: Principal = Depends(viewer), db: Session = Depends(get_db)) -> UsageOut:
    return UsageOut(**quota_service.usage(db, _org(db, p)))


# ---- members -------------------------------------------------------------------------------


def _member_out(db: Session, m: Membership) -> MemberOut:
    user = db.get(User, m.user_id)
    assert user is not None
    return MemberOut(user_id=user.id, email=user.email, role=m.role)


def _membership(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    m = db.scalars(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    ).first()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return m


@router.get("/{org_id}/members", response_model=list[MemberOut])
def members(p: Principal = Depends(viewer), db: Session = Depends(get_db)) -> list[MemberOut]:
    rows = db.scalars(
        select(Membership).where(Membership.org_id == p.org_id).order_by(Membership.created_at)
    )
    return [_member_out(db, m) for m in rows]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    data: MemberAdd,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> MemberOut:
    user = db.scalars(select(User).where(User.email == data.email.lower())).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No registered user with that email")
    exists = db.scalars(
        select(Membership).where(Membership.org_id == p.org_id, Membership.user_id == user.id)
    ).first()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")
    m = Membership(org_id=p.org_id, user_id=user.id, role=data.role)
    db.add(m)
    db.commit()
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="member.add", target_type="user",
        target_id=user.id, detail={"email": user.email, "role": data.role}, request=request,
    )  # fmt: skip
    return _member_out(db, m)


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
def change_role(
    user_id: uuid.UUID,
    data: MemberUpdate,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> MemberOut:
    m = _membership(db, p.org_id, user_id)
    if m.role == "admin" and data.role != "admin" and org_service.count_admins(db, p.org_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "An organization needs at least one admin")
    old, m.role = m.role, data.role
    db.commit()
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="member.role_change", target_type="user",
        target_id=user_id, detail={"from": old, "to": data.role}, request=request,
    )  # fmt: skip
    return _member_out(db, m)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> Response:
    m = _membership(db, p.org_id, user_id)
    if m.role == "admin" and org_service.count_admins(db, p.org_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "An organization needs at least one admin")
    db.delete(m)
    db.commit()
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="member.remove", target_type="user",
        target_id=user_id, request=request,
    )  # fmt: skip
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- audit, export, lifecycle ----------------------------------------------------------------


@router.get("/{org_id}/audit", response_model=list[AuditOut])
def audit(
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    return audit_service.list_entries(
        db, p.org_id, action=action, actor_id=actor_id, limit=limit, offset=offset
    )


@router.get("/{org_id}/export")
def export(
    request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)
) -> Response:
    org = _org(db, p)
    data = retention_service.export_org(db, org)
    audit_service.record(
        db, org_id=org.id, actor_id=p.user.id, action="org.export", target_type="org",
        target_id=org.id, detail={"bytes": len(data)}, request=request,
    )  # fmt: skip
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{org.slug}-export.zip"'},
    )


@router.post("/{org_id}/retention/run", response_model=RetentionOut)
def run_retention(
    request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)
) -> RetentionOut:
    org = _org(db, p)
    purged = retention_service.run_retention(db, org)
    audit_service.record(
        db, org_id=org.id, actor_id=p.user.id, action="org.retention_run", target_type="org",
        target_id=org.id, detail={"purged_tasks": purged, "retention_days": org.retention_days},
        request=request,
    )  # fmt: skip
    return RetentionOut(purged_tasks=purged)


@router.delete("/{org_id}/data", response_model=DeleteDataOut)
def delete_data(
    body: DeleteDataRequest,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> DeleteDataOut:
    """Irreversible: removes every project and task of the organization (needs the slug)."""
    org = _org(db, p)
    if body.confirm != org.slug:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "confirm must equal the org slug")
    audit_service.record(  # written BEFORE the deletion, so the intent survives any failure
        db, org_id=org.id, actor_id=p.user.id, action="org.delete_data", target_type="org",
        target_id=org.id, request=request,
    )  # fmt: skip
    return DeleteDataOut(deleted_tasks=retention_service.delete_org_data(db, org))
