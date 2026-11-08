"""SCIM 2.0 provisioning for one organization (Phase 17, RFC 7643/7644 subset).

Scope: Users (list/get/create/patch/delete) and Groups (the four fixed role groups: list/get/patch).
Everything is **per organization**: a SCIM token is bound to one org and can only see and change
that org's provisioned users. "Active" means the user holds a membership of this org; deactivating
removes that membership (sessions in this org end on the next request because roles are read from
the database per request) and never touches the account or the user's other organizations. If the
user has no organization left, the account is disabled and every session revoked.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Membership, ScimIdentity, ScimToken, User
from app.services import audit_service, auth_service, org_service

TOKEN_PREFIX = "lfs_"  # nosec B105 - a token prefix, not a password
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
MAX_PAGE = 200


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status, self.detail, self.scim_type = status, detail, scim_type

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schemas": [ERROR_SCHEMA], "status": str(self.status), "detail": self.detail
        }  # fmt: skip
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---- tokens ------------------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, name: str
) -> tuple[ScimToken, str]:
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ScimToken(
        org_id=org_id, name=name, prefix=secret[:8], token_hash=_hash(secret), created_by=user_id
    )
    db.add(row)
    db.commit()
    return row, secret


def authenticate(db: Session, bearer: str) -> ScimToken | None:
    if not bearer.startswith(TOKEN_PREFIX):
        return None
    row = db.scalars(select(ScimToken).where(ScimToken.token_hash == _hash(bearer))).first()
    if row is None or row.revoked_at is not None:
        return None
    row.last_used_at = _now()
    db.commit()
    return row


def list_tokens(db: Session, org_id: uuid.UUID) -> list[ScimToken]:
    return list(
        db.scalars(
            select(ScimToken).where(ScimToken.org_id == org_id).order_by(ScimToken.created_at)
        )
    )


def revoke_token(db: Session, org_id: uuid.UUID, token_id: uuid.UUID) -> ScimToken | None:
    row = db.get(ScimToken, token_id)
    if row is None or row.org_id != org_id:
        return None
    row.revoked_at = row.revoked_at or _now()
    db.commit()
    return row


# ---- resources ---------------------------------------------------------------------------------


def user_resource(user: User, ident: ScimIdentity) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schemas": [USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "active": ident.active,
        "emails": [{"value": user.email, "primary": True}],
        "meta": {"resourceType": "User", "created": ident.created_at.isoformat() + "Z"},
    }
    if ident.external_id:
        out["externalId"] = ident.external_id
    return out


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):  # Entra sends strings
        return value.lower() == "true"
    raise ScimError(400, "active must be a boolean", "invalidValue")


def _identity(db: Session, org_id: uuid.UUID, user_id: str) -> tuple[User, ScimIdentity]:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise ScimError(404, "User not found") from None
    ident = db.scalars(
        select(ScimIdentity).where(ScimIdentity.org_id == org_id, ScimIdentity.user_id == uid)
    ).first()
    user = db.get(User, uid)
    if ident is None or user is None:
        raise ScimError(404, "User not found")
    return user, ident


def get_user(db: Session, org_id: uuid.UUID, user_id: str) -> dict[str, Any]:
    return user_resource(*_identity(db, org_id, user_id))


def list_users(
    db: Session, org_id: uuid.UUID, flt: str | None, start: int, count: int
) -> dict[str, Any]:
    stmt = (
        select(User, ScimIdentity)
        .join(ScimIdentity, ScimIdentity.user_id == User.id)
        .where(ScimIdentity.org_id == org_id)
        .order_by(ScimIdentity.created_at, User.id)
    )
    if flt:
        attr, value = _parse_filter(flt)
        stmt = stmt.where(
            User.email == value.lower() if attr == "username" else ScimIdentity.external_id == value
        )
    rows = list(db.execute(stmt))
    count = max(0, min(count, MAX_PAGE))
    page = rows[max(start, 1) - 1 : max(start, 1) - 1 + count]
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": len(rows),
        "startIndex": max(start, 1),
        "itemsPerPage": len(page),
        "Resources": [user_resource(u, i) for u, i in page],
    }


def _parse_filter(flt: str) -> tuple[str, str]:
    parts = flt.strip().split(None, 2)
    if (
        len(parts) != 3
        or parts[1].lower() != "eq"
        or parts[0].lower() not in ("username", "externalid")
    ):
        raise ScimError(
            400, 'only filters of the form userName eq "x" / externalId eq "x"', "invalidFilter"
        )
    value = parts[2]
    if len(value) < 2 or value[0] != '"' or value[-1] != '"':
        raise ScimError(400, "filter value must be a quoted string", "invalidFilter")
    return parts[0].lower(), value[1:-1]


def create_user(db: Session, org_id: uuid.UUID, body: dict[str, Any]) -> dict[str, Any]:
    email = str(body.get("userName", "")).strip().lower()
    if "@" not in email or len(email) > 254:
        raise ScimError(400, "userName must be an email address", "invalidValue")
    role = "developer"
    for r in body.get("roles") or []:
        value = r.get("value") if isinstance(r, dict) else None
        if value in org_service.ROLE_RANK:
            role = value
            break
    active = _as_bool(body["active"]) if "active" in body else True
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is not None:
        taken = db.scalars(
            select(ScimIdentity).where(
                ScimIdentity.org_id == org_id, ScimIdentity.user_id == user.id
            )
        ).first()
        member = db.scalars(
            select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
        ).first()
        if taken is not None or member is not None:
            raise ScimError(409, "a user with this userName already exists", "uniqueness")
    else:
        user = User(
            email=email, password_hash=None, email_verified_at=_now(), active=True
        )  # the org's IdP vouches for the address; there is no password, sign-in is SSO
        user.id = uuid.uuid4()
        db.add(user)
        db.flush()
    ext = body.get("externalId")
    ident = ScimIdentity(
        org_id=org_id, user_id=user.id, external_id=str(ext) if ext else None, active=active
    )
    db.add(ident)
    if active:
        db.add(Membership(org_id=org_id, user_id=user.id, role=role, source="scim"))
    db.commit()
    audit_service.record(
        db, org_id=org_id, actor_id=None, action="scim.user_created", target_type="user",
        target_id=user.id, detail={"role": role, "active": active},
    )  # fmt: skip
    return user_resource(user, ident)


def _set_active(
    db: Session, org_id: uuid.UUID, user: User, ident: ScimIdentity, active: bool
) -> None:
    if active == ident.active:
        return
    member = db.scalars(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
    ).first()
    if not active:
        if member is not None:
            if member.role == "admin" and org_service.count_admins(db, org_id) <= 1:
                raise ScimError(
                    409, "cannot deactivate the organization's last admin", "mutability"
                )
            db.delete(member)
        ident.active = False
        db.flush()
        remaining = org_service.memberships_of(db, user.id)
        if not remaining:  # nothing left to sign in to: end every session
            user.active = False
            user.token_version += 1
            auth_service.revoke_all(db, user)
    else:
        if member is None:
            db.add(Membership(org_id=org_id, user_id=user.id, role="developer", source="scim"))
        ident.active = True
        user.active = True
    db.commit()
    audit_service.record(
        db, org_id=org_id, actor_id=None,
        action="scim.user_activated" if active else "scim.user_deactivated",
        target_type="user", target_id=user.id,
    )  # fmt: skip


def patch_user(
    db: Session, org_id: uuid.UUID, user_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    user, ident = _identity(db, org_id, user_id)
    ops = body.get("Operations")
    if PATCH_SCHEMA not in (body.get("schemas") or []) or not isinstance(ops, list) or not ops:
        raise ScimError(400, "a PatchOp with Operations is required", "invalidSyntax")
    for op in ops:
        name = str(op.get("op", "")).lower() if isinstance(op, dict) else ""
        if name not in ("add", "replace", "remove"):
            raise ScimError(400, "unsupported operation", "invalidSyntax")
        path, value = op.get("path"), op.get("value")
        values = {path: value} if path else (value if isinstance(value, dict) else None)
        if values is None:
            raise ScimError(400, "operation needs a path or an object value", "invalidSyntax")
        for attr, val in values.items():
            key = str(attr).lower()
            if key == "active":
                _set_active(db, org_id, user, ident, _as_bool(val))
            elif key == "externalid":
                ident.external_id = None if name == "remove" or val in (None, "") else str(val)
                db.commit()
            elif key == "username":
                if str(val).lower() != user.email:
                    raise ScimError(400, "userName cannot be changed", "mutability")
            else:
                raise ScimError(400, f"attribute {attr} is not supported", "invalidPath")
    return user_resource(user, ident)


def delete_user(db: Session, org_id: uuid.UUID, user_id: str) -> None:
    """DELETE = deprovision from this org (the SCIM record is kept, inactive)."""
    user, ident = _identity(db, org_id, user_id)
    _set_active(db, org_id, user, ident, False)


# ---- groups: the four role groups --------------------------------------------------------------


def _group(db: Session, org_id: uuid.UUID, role: str) -> dict[str, Any]:
    members = db.execute(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .join(ScimIdentity, (ScimIdentity.user_id == User.id) & (ScimIdentity.org_id == org_id))
        .where(Membership.org_id == org_id, Membership.role == role)
        .order_by(User.email)
    ).scalars()
    return {
        "schemas": [GROUP_SCHEMA],
        "id": role,
        "displayName": role,
        "members": [{"value": str(u.id), "display": u.email} for u in members],
        "meta": {"resourceType": "Group"},
    }


def list_groups(db: Session, org_id: uuid.UUID) -> dict[str, Any]:
    groups = [_group(db, org_id, r) for r in org_service.ROLE_RANK]
    return {
        "schemas": [LIST_SCHEMA], "totalResults": len(groups), "startIndex": 1,
        "itemsPerPage": len(groups), "Resources": groups,
    }  # fmt: skip


def get_group(db: Session, org_id: uuid.UUID, group_id: str) -> dict[str, Any]:
    if group_id not in org_service.ROLE_RANK:
        raise ScimError(404, "Group not found")
    return _group(db, org_id, group_id)


def patch_group(
    db: Session, org_id: uuid.UUID, group_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """add members -> they get this role; remove -> they fall to 'viewer' (never deleted)."""
    if group_id not in org_service.ROLE_RANK:
        raise ScimError(404, "Group not found")
    ops = body.get("Operations")
    if PATCH_SCHEMA not in (body.get("schemas") or []) or not isinstance(ops, list) or not ops:
        raise ScimError(400, "a PatchOp with Operations is required", "invalidSyntax")
    for op in ops:
        name = str(op.get("op", "")).lower() if isinstance(op, dict) else ""
        path = str(op.get("path", "")).lower()
        if name not in ("add", "remove") or not path.startswith("members"):
            raise ScimError(400, "only add/remove on members is supported", "invalidPath")
        for value in _member_ids(op):
            _regroup(db, org_id, value, group_id if name == "add" else "viewer")
    return _group(db, org_id, group_id)


def _member_ids(op: dict[str, Any]) -> list[str]:
    ids = [str(m.get("value")) for m in (op.get("value") or []) if isinstance(m, dict)]
    path = str(op.get("path", ""))
    if '"' in path:  # members[value eq "uuid"]
        ids.append(path.split('"')[1])
    return [i for i in ids if i]


def _regroup(db: Session, org_id: uuid.UUID, user_id: str, role: str) -> None:
    user, ident = _identity(db, org_id, user_id)
    member = db.scalars(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
    ).first()
    if member is None or not ident.active:
        raise ScimError(400, "user is not an active member of this organization", "invalidValue")
    if member.role == role:
        return
    if member.role == "admin" and org_service.count_admins(db, org_id) <= 1:
        raise ScimError(409, "cannot demote the organization's last admin", "mutability")
    old, member.role, member.source = member.role, role, "scim"
    db.commit()
    audit_service.record(
        db, org_id=org_id, actor_id=None, action="scim.role_changed", target_type="user",
        target_id=user.id, detail={"from": old, "to": role},
    )  # fmt: skip
