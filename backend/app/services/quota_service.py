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

from app.database.models import AgentRun, Iteration, Organization, Project, Task


class QuotaExceeded(Exception):
    """An organization quota stops the request (mapped to HTTP 429)."""


def month_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def tokens_used(db: Session, org_id: uuid.UUID, now: datetime | None = None) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(AgentRun.tokens_used), 0))
            .join(Iteration, AgentRun.iteration_id == Iteration.id)
            .join(Task, Iteration.task_id == Task.id)
            .join(Project, Task.project_id == Project.id)
            .where(Project.org_id == org_id, AgentRun.started_at >= month_start(now))
        )
        or 0
    )


def tasks_created(db: Session, org_id: uuid.UUID, now: datetime | None = None) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Task)
            .join(Project, Task.project_id == Project.id)
            .where(Project.org_id == org_id, Task.created_at >= month_start(now))
        )
        or 0
    )


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


def check_can_create_task(db: Session, org_id: uuid.UUID) -> None:
    org = db.get(Organization, org_id)
    if org is not None and org.max_tasks_month is not None:
        if tasks_created(db, org_id) >= org.max_tasks_month:
            raise QuotaExceeded(f"monthly task quota reached ({org.max_tasks_month})")


def check_can_start(db: Session, org_id: uuid.UUID) -> None:
    org = db.get(Organization, org_id)
    if org is not None and org.token_quota_month is not None:
        if tokens_used(db, org_id) >= org.token_quota_month:
            raise QuotaExceeded(f"monthly token quota reached ({org.token_quota_month})")


def token_ceiling(db: Session, task: Task, already_used_by_task: int) -> int | None:
    """Largest total token count this task may reach without exceeding the org's month, or None."""
    org = db.get(Organization, task.project.org_id)
    if org is None or org.token_quota_month is None:
        return None
    other = tokens_used(db, org.id) - already_used_by_task  # this task's tokens are already counted
    return max(0, org.token_quota_month - max(0, other))
