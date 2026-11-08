"""Job queue for the worker service (ADR-0014).

The API enqueues a `start`/`resume` job instead of running the loop in its own process; any number
of workers claim jobs. A claim is a conditional UPDATE (queued -> running), so exactly one worker
wins each job on SQLite and Postgres alike. The per-task run lease still guards against two
workers driving the same task if two jobs for it ever exist.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Job, RunLease, Task
from app.services import lease_service, run_service
from app.services.task_service import TaskStatus
from app.utils.metrics import JOBS_FINISHED

log = logging.getLogger("loopforge.jobs")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _pending(db: Session, task_id: uuid.UUID) -> Job | None:
    return db.scalars(
        select(Job).where(Job.task_id == task_id, Job.status.in_(("queued", "running")))
    ).first()


def enqueue(db: Session, task_id: uuid.UUID, kind: str, request_id: str | None = None) -> Job:
    """Queue a job unless one for the task is already pending (idempotent for double clicks).

    `request_id` is the HTTP request that caused the job; the worker logs with it (Phase 12).
    """
    existing = _pending(db, task_id)
    if existing is not None:
        return existing
    job = Job(task_id=task_id, kind=kind, request_id=request_id)
    db.add(job)
    db.commit()
    return job


def claim_next(db: Session, worker: str) -> Job | None:
    candidates = db.scalars(
        select(Job.id).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(5)
    ).all()
    for job_id in candidates:
        won = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", claimed_by=worker, claimed_at=_now())
        )
        db.commit()
        if won.rowcount == 1:
            db.expire_all()
            return db.get(Job, job_id)
    return None


def finish(db: Session, job_id: uuid.UUID, status: str, error: str = "") -> None:
    db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status=status, error=error[:500], finished_at=_now())
    )
    db.commit()
    JOBS_FINISHED.inc(status=status)


def recover(db: Session) -> int:
    """Fail jobs whose worker died (running, no live lease) and re-queue a resume if needed.

    Returns the number of resume jobs queued. Safe to run from every worker concurrently.
    """
    grace = _now() - timedelta(seconds=settings.lease_ttl_seconds)
    stale = db.scalars(select(Job).where(Job.status == "running", Job.claimed_at < grace)).all()
    for job in stale:
        lease: RunLease | None = db.get(RunLease, job.task_id)
        if lease is not None and lease.expires_at >= _now():
            continue  # the owner is alive, just slow
        finish(db, job.id, "failed", "worker lost")
    queued = 0
    for task_id in run_service.interrupted_task_ids(db):
        if lease_service.is_held(db, task_id) or _pending(db, task_id) is not None:
            continue
        task = db.get(Task, task_id)
        if task is not None and TaskStatus(task.status) != TaskStatus.PENDING:
            enqueue(db, task_id, "resume")
            queued += 1
    return queued
