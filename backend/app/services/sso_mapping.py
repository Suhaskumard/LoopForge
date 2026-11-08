"""SSO group -> organization role mapping (Phase 17).

Configuration (both optional; with neither set, SSO behaves exactly as in Phase 10):

* ``OIDC_GROUPS_CLAIM``  - the ID-token claim holding the user's groups (default ``groups``).
* ``OIDC_GROUP_ROLE_MAP_JSON`` - ``{"lf-admins": {"org": "<slug>", "role": "admin"}, ...}``.
* ``OIDC_DOMAIN_ORG_MAP_JSON`` - ``{"acme.com": {"org": "<slug>", "role": "developer"}}``: a
  verified email domain joins that org at that role even without a group (the baseline).

On every SSO login, for each organization named in either map: the user's role there becomes the
highest role they qualify for. Only memberships whose ``source`` is ``sso`` are changed or removed -
anything an admin granted by hand (``manual``) or SCIM manages (``scim``) is left alone. A change
that would remove or demote the organization's last admin is skipped and audited. Every change is
audited. Unknown roles/orgs in the map are ignored (logged), never granted.
"""

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Membership, Organization, User
from app.services import audit_service, org_service

log = logging.getLogger("loopforge.sso")


def _load(raw: str) -> dict[str, dict[str, str]]:
    if not raw.strip():
        return {}
    data = json.loads(raw)
    return {
        str(k): {"org": str(v["org"]), "role": str(v["role"])}
        for k, v in data.items()
        if isinstance(v, dict) and v.get("role") in org_service.ROLE_RANK and v.get("org")
    }


def validate_config(group_map: str, domain_map: str) -> None:
    """Raise ValueError at startup for malformed JSON or unknown roles."""
    for name, raw in (
        ("OIDC_GROUP_ROLE_MAP_JSON", group_map),
        ("OIDC_DOMAIN_ORG_MAP_JSON", domain_map),
    ):
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
            ok = isinstance(data, dict) and all(
                isinstance(v, dict)
                and isinstance(v.get("org"), str)
                and v["org"]
                and v.get("role") in org_service.ROLE_RANK
                for v in data.values()
            )
        except ValueError:
            ok = False
        if not ok:
            raise ValueError(
                f'{name} must be a JSON object of {{"key": {{"org": "<slug>", "role": '
                f'"viewer|developer|approver|admin"}}}}'
            )


def enabled() -> bool:
    return bool(
        settings.oidc_group_role_map_json.strip() or settings.oidc_domain_org_map_json.strip()
    )


def _groups(claims: dict[str, Any]) -> set[str]:
    raw = claims.get(settings.oidc_groups_claim, [])
    if isinstance(raw, str):
        raw = [raw]
    return {str(g) for g in raw} if isinstance(raw, list) else set()


def desired_roles(claims: dict[str, Any], email: str) -> dict[str, str | None]:
    """org slug -> highest qualifying role (None: mapped org, user qualifies for nothing)."""
    group_map = _load(settings.oidc_group_role_map_json)
    domain_map = _load(settings.oidc_domain_org_map_json)
    out: dict[str, str | None] = {
        v["org"]: None for v in (*group_map.values(), *domain_map.values())
    }
    domain = email.rsplit("@", 1)[-1].lower()
    matches = [group_map[g] for g in _groups(claims) if g in group_map]
    if domain in {d.lower() for d in domain_map}:
        matches.append(next(v for d, v in domain_map.items() if d.lower() == domain))
    for m in matches:
        cur = out[m["org"]]
        if cur is None or org_service.ROLE_RANK[m["role"]] > org_service.ROLE_RANK[cur]:
            out[m["org"]] = m["role"]
    return out


def apply(db: Session, user: User, claims: dict[str, Any]) -> list[str]:
    """Reconcile this user's SSO-managed memberships; returns a list of human-readable changes."""
    if not enabled():
        return []
    changes: list[str] = []
    for slug, role in desired_roles(claims, user.email).items():
        org = db.scalars(select(Organization).where(Organization.slug == slug)).first()
        if org is None:
            log.warning("sso mapping names unknown organization %r - ignored", slug)
            continue
        member = db.scalars(
            select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id)
        ).first()
        action = _reconcile(db, org.id, user.id, member, role)
        if action:
            changes.append(f"{slug}:{action}")
    return changes


def _reconcile(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, member: Membership | None, role: str | None
) -> str:
    def audit(action: str, detail: dict[str, Any]) -> None:
        audit_service.record(
            db, org_id=org_id, actor_id=user_id, action=action, target_type="membership",
            target_id=str(user_id), detail={"source": "sso", **detail},
        )  # fmt: skip

    if member is None:
        if role is None:
            return ""
        db.add(Membership(org_id=org_id, user_id=user_id, role=role, source="sso"))
        db.commit()
        audit("sso.member_added", {"role": role})
        return f"added as {role}"
    if member.source != "sso":
        return ""  # a human or SCIM owns this membership
    last_admin = member.role == "admin" and org_service.count_admins(db, org_id) <= 1
    if role is None:
        if last_admin:
            audit("sso.change_skipped", {"reason": "last admin", "wanted": "remove"})
            return ""
        db.delete(member)
        db.commit()
        audit("sso.member_removed", {"was": member.role})
        return "removed"
    if role == member.role:
        return ""
    if last_admin and role != "admin":
        audit("sso.change_skipped", {"reason": "last admin", "wanted": role})
        return ""
    old, member.role = member.role, role
    db.commit()
    audit("sso.role_changed", {"from": old, "to": role})
    return f"{old}->{role}"
