"""Scrape-time gauges for state that lives in the database (Phase 12, ADR-0019).

Everything here is a cheap aggregate query, computed when /metrics is read, so every API replica
reports the same numbers. Nothing per-user or per-task is exported: labels are statuses only.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Job, RunLease, Task
from app.services import quota_service
from app.utils import metrics as m

VERSION = "12"


def refresh_db_gauges(db: Session, now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)

    m.TASKS.clear()
    for status, count in db.execute(select(Task.status, func.count()).group_by(Task.status)):
        m.TASKS.set(count, status=status)

    queued = db.execute(
        select(func.count(), func.min(Job.created_at)).where(Job.status == "queued")
    ).one()
    m.JOBS_QUEUED.set(queued[0] or 0)
    m.JOBS_OLDEST_QUEUED_AGE.set(
        max(0.0, (current - queued[1]).total_seconds()) if queued[1] is not None else 0
    )
    m.JOBS_RUNNING.set(
        db.scalar(select(func.count()).select_from(Job).where(Job.status == "running")) or 0
    )

    m.ACTIVE_LEASES.set(
        db.scalar(select(func.count()).select_from(RunLease).where(RunLease.expires_at >= current))
        or 0
    )
    m.EXPIRED_LEASES.set(
        db.scalar(select(func.count()).select_from(RunLease).where(RunLease.expires_at < current))
        or 0
    )
    m.TOKENS_MONTH.set(_tokens_this_month(db, current))
    m.BUILD_INFO.set(1, version=VERSION)


def _tokens_this_month(db: Session, now: datetime) -> int:
    from app.database.models import AgentRun

    return int(
        db.scalar(
            select(func.coalesce(func.sum(AgentRun.tokens_used), 0)).where(
                AgentRun.started_at >= quota_service.month_start(now)
            )
        )
        or 0
    )
