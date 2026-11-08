"""Per-organization monthly quotas (Phase 10, ADR-0017), enforced by the server.

Usage is computed from the same rows the analytics use (`agent_runs.tokens_used`, `tasks`), per
calendar month (UTC). A quota of NULL means "no cap". Token usage is an estimate of model tokens,
not billing data. Quotas are checked when a task is created and when a run starts, and the run
itself is capped at what is left (`token_ceiling`), so one task cannot overshoot the month.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import AgentRun, Iteration, Membership, Organization, Project, Task


class QuotaExceeded(Exception):
    """An organization quota stops the request (mapped to HTTP 429)."""


def month_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def tokens_used(
    db: Session, org_id: uuid.UUID, now: datetime | None = None, user_id: uuid.UUID | None = None
) -> int:
    """Tokens used this month in the org; with `user_id`, only by tasks that member created."""
    q = (
        select(func.coalesce(func.sum(AgentRun.tokens_used), 0))
        .join(Iteration, AgentRun.iteration_id == Iteration.id)
        .join(Task, Iteration.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .where(Project.org_id == org_id, AgentRun.started_at >= month_start(now))
    )
    if user_id is not None:
        q = q.where(Task.created_by == user_id)
    return int(db.scalar(q) or 0)


def tasks_created(
    db: Session, org_id: uuid.UUID, now: datetime | None = None, user_id: uuid.UUID | None = None
) -> int:
    q = (
        select(func.count())
        .select_from(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Project.org_id == org_id, Task.created_at >= month_start(now))
    )
    if user_id is not None:
        q = q.where(Task.created_by == user_id)
    return int(db.scalar(q) or 0)


def _member(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None) -> Membership | None:
    if user_id is None:
        return None
    return db.scalars(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    ).first()


def member_usage(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None
) -> dict[str, int | None]:
    """The same shape as `usage`, for one member's own caps (NULL = no personal cap)."""
    m = _member(db, org_id, user_id)
    used, created = tokens_used(db, org_id, now, user_id), tasks_created(db, org_id, now, user_id)
    tq = m.token_quota_month if m else None
    tm = m.max_tasks_month if m else None
    return {
        "tokens_used": used,
        "token_quota_month": tq,
        "tokens_remaining": None if tq is None else max(0, tq - used),
        "tasks_created": created,
        "max_tasks_month": tm,
        "tasks_remaining": None if tm is None else max(0, tm - created),
    }


def warnings(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None = None, now: datetime | None = None
) -> list[dict[str, object]]:
    """Quotas at or past `quota_warn_fraction` of their cap, for the org and the member."""
    from app.config import settings

    org = db.get(Organization, org_id)
    out: list[dict[str, object]] = []
    scopes: list[tuple[str, dict[str, int | None]]] = []
    if org is not None:
        scopes.append(("org", usage(db, org, now)))
    if user_id is not None:
        scopes.append(("member", member_usage(db, org_id, user_id, now)))
    for scope, u in scopes:
        for used_key, cap_key, label in (
            ("tokens_used", "token_quota_month", "tokens"),
            ("tasks_created", "max_tasks_month", "tasks"),
        ):
            cap, used = u[cap_key], u[used_key] or 0
            if cap and used >= cap * settings.quota_warn_fraction:
                out.append({"scope": scope, "resource": label, "used": used, "cap": cap})
    return out


def usage(db: Session, org: Organization, now: datetime | None = None) -> dict[str, int | None]:
    used, created = tokens_used(db, org.id, now), tasks_created(db, org.id, now)
    return {
        "tokens_used": used,
        "token_quota_month": org.token_quota_month,
        "tokens_remaining": None
        if org.token_quota_month is None
        else max(0, org.token_quota_month - used),
        "tasks_created": created,
        "max_tasks_month": org.max_tasks_month,
        "tasks_remaining": None
        if org.max_tasks_month is None
        else max(0, org.max_tasks_month - created),
    }


def check_can_create_task(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None = None) -> None:
    org = db.get(Organization, org_id)
    if org is not None and org.max_tasks_month is not None:
        if tasks_created(db, org_id) >= org.max_tasks_month:
            raise QuotaExceeded(f"monthly task quota reached ({org.max_tasks_month})")
    m = _member(db, org_id, user_id)
    if m is not None and m.max_tasks_month is not None:
        if tasks_created(db, org_id, user_id=user_id) >= m.max_tasks_month:
            raise QuotaExceeded(f"your monthly task quota is reached ({m.max_tasks_month})")


def check_can_start(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None = None) -> None:
    org = db.get(Organization, org_id)
    if org is not None and org.token_quota_month is not None:
        if tokens_used(db, org_id) >= org.token_quota_month:
            raise QuotaExceeded(f"monthly token quota reached ({org.token_quota_month})")
    m = _member(db, org_id, user_id)
    if m is not None and m.token_quota_month is not None:
        if tokens_used(db, org_id, user_id=user_id) >= m.token_quota_month:
            raise QuotaExceeded(f"your monthly token quota is reached ({m.token_quota_month})")


def token_ceiling(db: Session, task: Task, already_used_by_task: int) -> int | None:
    """Largest total token count this task may reach without exceeding the org's month, or None.

    With a per-member cap on the task's creator, the lower of the two remainders wins.
    """
    org = db.get(Organization, task.project.org_id)
    if org is None:
        return None
    ceilings: list[int] = []
    if org.token_quota_month is not None:
        other = tokens_used(db, org.id) - already_used_by_task  # this task's tokens already counted
        ceilings.append(max(0, org.token_quota_month - max(0, other)))
    m = _member(db, org.id, task.created_by)
    if m is not None and m.token_quota_month is not None:
        mine = tokens_used(db, org.id, user_id=task.created_by) - already_used_by_task
        ceilings.append(max(0, m.token_quota_month - max(0, mine)))
    return min(ceilings) if ceilings else None
