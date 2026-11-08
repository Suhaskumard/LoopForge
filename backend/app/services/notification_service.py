"""Notifications (Phase 15): in-app rows + email + webhook for the same event.

Triggers: a task finishing, an approval waiting, a quota nearing its cap. Everything here is
best effort - a notification failure must never change the outcome of the action that caused it.
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Membership, Notification, User
from app.services import mail_service, quota_service, webhook_service

log = logging.getLogger("loopforge.notifications")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _recipients(
    db: Session,
    org_id: uuid.UUID,
    roles: Iterable[str] | None,
    user_ids: Iterable[uuid.UUID] | None,
) -> list[User]:
    q = (
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id)
    )
    if roles is not None:
        q = q.where(Membership.role.in_(list(roles)))
    if user_ids is not None:
        q = q.where(User.id.in_(list(user_ids)))
    return list(db.scalars(q))


def notify(
    db: Session,
    org_id: uuid.UUID,
    kind: str,
    title: str,
    detail: dict[str, Any],
    *,
    roles: Iterable[str] | None = None,
    user_ids: Iterable[uuid.UUID] | None = None,
    dedupe_key: str | None = None,
    webhook: bool = True,
) -> int:
    """Create in-app notifications (and emails) for the matching org members. Returns the count."""
    created = 0
    for user in _recipients(db, org_id, roles, user_ids):
        db.add(
            Notification(
                user_id=user.id, org_id=org_id, kind=kind, title=title, detail=detail,
                dedupe_key=dedupe_key,
            )
        )  # fmt: skip
        try:
            db.commit()
        except IntegrityError:  # the same event was already delivered to this user
            db.rollback()
            continue
        created += 1
        if user.notify_email:
            body = f"{title}\n\n{mail_service.link('', '').split('?')[0]}"
            mail_service.send(user.email, f"LoopForge: {title}", body)
    if webhook and created:
        webhook_service.emit_safely(db, org_id, kind, {"title": title, **detail})
    return created


def notify_safely(*args: Any, **kwargs: Any) -> int:
    db: Session = args[0]
    try:
        return notify(*args, **kwargs)
    except Exception:
        log.exception("could not create notification")
        db.rollback()
        return 0


def check_quota_warnings(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """Notify once per month per quota when usage reaches QUOTA_WARN_FRACTION of a cap."""
    try:
        month = quota_service.month_start().strftime("%Y-%m")
        for w in quota_service.warnings(db, org_id, user_id):
            title = (
                f"{str(w['scope']).capitalize()} {w['resource']} quota at "
                f"{w['used']} of {w['cap']} this month"
            )
            if w["scope"] == "org":
                notify(
                    db, org_id, "quota.near_limit", title, dict(w), roles=("admin",),
                    dedupe_key=f"quota:org:{w['resource']}:{month}",
                )  # fmt: skip
            elif user_id is not None:
                notify(
                    db, org_id, "quota.near_limit", title, dict(w), user_ids=[user_id],
                    dedupe_key=f"quota:member:{w['resource']}:{month}", webhook=False,
                )  # fmt: skip
    except Exception:
        log.exception("quota warning check failed")
        db.rollback()


# ---- reading / marking (used by the API) ---------------------------------------------------


def list_for(db: Session, user: User, *, unread_only: bool, limit: int) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return list(db.scalars(q.order_by(Notification.created_at.desc()).limit(limit)))


def unread_count(db: Session, user: User) -> int:
    return len(list_for(db, user, unread_only=True, limit=1000))


def mark_read(db: Session, user: User, notification_id: uuid.UUID | None) -> int:
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if notification_id is not None:
        q = q.where(Notification.id == notification_id)
    n = db.execute(q.values(read_at=_now())).rowcount
    db.commit()
    return int(n)
