import uuid
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditEvent, Project, Task


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    REPAIRING = "REPAIRING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
# Halted by the system (not by the user, not successful): a user may retry them (Phase 4).
RETRYABLE_STATES = {TaskStatus.FAILED, TaskStatus.ESCALATED}

_ABORTS = {TaskStatus.FAILED, TaskStatus.ESCALATED, TaskStatus.CANCELLED}

# Spec 7.3: PENDING -> PLANNING -> GENERATING -> EXECUTING -> TESTING -> REVIEWING
# -> (REPAIRING -> back to EXECUTING) -> terminal.
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {TaskStatus.GENERATING} | _ABORTS,
    TaskStatus.GENERATING: {TaskStatus.EXECUTING, TaskStatus.AWAITING_APPROVAL} | _ABORTS,
    TaskStatus.EXECUTING: {TaskStatus.TESTING} | _ABORTS,
    TaskStatus.TESTING: {TaskStatus.REVIEWING, TaskStatus.REPAIRING} | _ABORTS,
    TaskStatus.REVIEWING: {TaskStatus.REPAIRING, TaskStatus.COMPLETED} | _ABORTS,
    TaskStatus.REPAIRING: {TaskStatus.EXECUTING, TaskStatus.AWAITING_APPROVAL} | _ABORTS,
    # Paused for a human decision; resumes where it left off (GENERATING or REPAIRING).
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.GENERATING, TaskStatus.REPAIRING} | _ABORTS,
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.PENDING},
    TaskStatus.ESCALATED: {TaskStatus.PENDING},
    TaskStatus.CANCELLED: set(),
}


class InvalidTransition(Exception):
    pass


def can_transition(current: TaskStatus, new: TaskStatus) -> bool:
    return new in ALLOWED_TRANSITIONS[current]


def create_task(
    db: Session,
    project: Project,
    requirement: str,
    max_iterations: int,
    acceptance_criteria: list[str],
    *,
    token_budget: int | None = None,
    max_cost: float | None = None,
    require_plan_approval: bool = False,
    source_type: str = "none",
    source_ref: str | None = None,
    created_by: uuid.UUID | None = None,
    learn_from_task: bool = True,
) -> Task:
    task = Task(
        learn_from_task=learn_from_task,
        created_by=created_by,
        project_id=project.id,
        requirement=requirement,
        max_iterations=max_iterations,
        acceptance_criteria=acceptance_criteria,
        token_budget=token_budget,
        max_cost=max_cost,
        require_plan_approval=require_plan_approval,
        source_type=source_type,
        source_ref=source_ref,
        status=TaskStatus.PENDING.value,
    )
    db.add(task)
    db.flush()
    db.add(AuditEvent(task_id=task.id, event_type="task_created", event_data={}))
    db.commit()
    return task


def transition(db: Session, task: Task, new: TaskStatus) -> Task:
    current = TaskStatus(task.status)
    if not can_transition(current, new):
        raise InvalidTransition(f"{current.value} -> {new.value} is not allowed")
    task.status = new.value
    db.add(
        AuditEvent(
            task_id=task.id,
            event_type="status_changed",
            event_data={"from": current.value, "to": new.value},
        )
    )
    db.commit()
    return task


def get_owned_task(db: Session, org_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
    stmt = (
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.id == task_id, Project.org_id == org_id)
    )
    return db.scalars(stmt).first()


def get_owned_task_for_update(db: Session, org_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
    """Like get_owned_task but takes a row lock (no-op on SQLite) to serialise transitions."""
    stmt = (
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.id == task_id, Project.org_id == org_id)
        .with_for_update(of=Task)
    )
    return db.scalars(stmt).first()


def list_task_events(db: Session, task: Task) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.task_id == task.id).order_by(AuditEvent.created_at)
    return list(db.scalars(stmt))


def list_owned_tasks(
    db: Session, org_id: uuid.UUID, limit: int = 50, offset: int = 0, order: str = "asc"
) -> list[Task]:
    newest = order == "desc"
    stmt = (
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Project.org_id == org_id)
        .order_by(Task.created_at.desc() if newest else Task.created_at, Task.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))
