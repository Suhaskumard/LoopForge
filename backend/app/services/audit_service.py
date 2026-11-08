"""Organization audit log (Phase 10, ADR-0017): who did what, append-only.

Rows are written here and nowhere else. The database refuses UPDATE and DELETE on `audit_log`
(triggers in migration 0006), so the history cannot be rewritten even by application bugs. Every
string in `detail` is passed through secret redaction first (and PII redaction when the
organization turned it on).
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Organization
from app.utils.client_ip import client_ip
from app.utils.redact import redact, redact_pii


def _clean(value: Any, pii: bool) -> Any:
    if isinstance(value, str):
        text = redact(value)
        return redact_pii(text) if pii else text
    if isinstance(value, dict):
        return {str(k): _clean(v, pii) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, pii) for v in value]
    return value


def record(
    db: Session,
    *,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str = "",
    target_id: str | uuid.UUID = "",
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> AuditLog:
    org = db.get(Organization, org_id) if org_id is not None else None
    tok = getattr(getattr(request, "state", None), "api_token", None)
    if tok is not None:  # Phase 11: calls made with an API token say so
        detail = {**(detail or {}), "api_token": str(tok.id)}
    row = AuditLog(
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=_clean(detail or {}, bool(org and org.redact_pii)),
        ip=client_ip(request) if request is not None else "",
    )
    db.add(row)
    if commit:
        db.commit()
    return row


def list_entries(
    db: Session,
    org_id: uuid.UUID,
    *,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.org_id == org_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    return list(
        db.scalars(
            stmt.order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit).offset(offset)
        )
    )
