"""Round 12: auto pipelines. Steps run in order; when a step's task is ACCEPTED the next step's
task is created as a chain from it (it starts from that accepted code) and started. A failed step
pauses the pipeline and tells its owner; `resume` retries that step.

`advance` is called from the terminal hook for every finished task; for a task that is not a
running pipeline step it does nothing (one indexed lookup).
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.models import Pipeline, PipelineStep, Project, Task
from app.schemas.advanced import StepIn
from app.services import intel_service, notification_service, task_service

log = logging.getLogger("loopforge.pipelines")

FINISHED = ("COMPLETED", "FAILED", "ESCALATED", "CANCELLED")


class PipelineError(Exception):
    pass


def create(
    db: Session,
    org_id: uuid.UUID,
    project: Project,
    name: str,
    steps: list[StepIn],
    actor: uuid.UUID,
) -> Pipeline:
    p = Pipeline(
        org_id=org_id, project_id=project.id, name=name.strip(), status="draft", created_by=actor
    )
    p.steps = [
        PipelineStep(
            position=i,
            requirement=s.requirement.strip(),
            acceptance_criteria=list(s.acceptance_criteria),
            max_iterations=s.max_iterations,
            status="pending",
        )  # fmt: skip
        for i, s in enumerate(steps)
    ]
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _project(db: Session, p: Pipeline) -> Project:
    project = db.get(Project, p.project_id)
    if project is None:
        raise PipelineError("the pipeline's project no longer exists")
    return project


def _launch(
    db: Session, p: Pipeline, step: PipelineStep, after: Task | None, actor: Any, starter: Any
) -> Task:
    """Create and start the task for `step`, chained from `after` when there is one."""
    task = task_service.create_task(
        db, _project(db, p), step.requirement, step.max_iterations, list(step.acceptance_criteria),
        source_type="task" if after is not None else "none",
        source_ref=str(after.id) if after is not None else None,
        created_by=actor,
    )  # fmt: skip
    if after is not None:
        try:
            intel_service.seed_from_task(db, task, after)
        except intel_service.IntelError:
            db.delete(task)
            db.commit()
            raise
    step.task_id = task.id
    step.status = "running"
    p.status = "running"
    db.commit()
    intel_service.start(db, task, starter)
    return task


def start(db: Session, p: Pipeline, actor: uuid.UUID, starter: Any) -> Pipeline:
    if p.status != "draft":
        raise PipelineError(f"the pipeline is {p.status}; only a draft can be started")
    _launch(db, p, p.steps[0], None, actor, starter)
    db.refresh(p)
    return p


def pause(db: Session, p: Pipeline) -> Pipeline:
    if p.status != "running":
        raise PipelineError(f"the pipeline is {p.status}; only a running one can be paused")
    p.status = "paused"  # the current step finishes; the next one will not start
    db.commit()
    db.refresh(p)
    return p


def resume(db: Session, p: Pipeline, actor: uuid.UUID, starter: Any) -> Pipeline:
    from app.services import run_service

    if p.status not in ("paused", "failed"):
        raise PipelineError(f"the pipeline is {p.status}; only a paused one can be resumed")
    prev: Task | None = None
    for step in p.steps:
        task = db.get(Task, step.task_id) if step.task_id else None
        if step.status == "accepted" or (task is not None and task.status == "COMPLETED"):
            step.status = "accepted"
            prev = task
            continue
        if task is not None and task.status in ("FAILED", "ESCALATED"):
            run_service.prepare_retry(db, task)
            step.status = "running"
            p.status = "running"
            db.commit()
            intel_service.start(db, task, starter)
        elif task is not None and task.status not in FINISHED:
            p.status = "running"  # still running: the hook will advance it when it finishes
            db.commit()
        else:  # never started, or cancelled: a fresh task for this step
            _launch(db, p, step, prev, actor, starter)
        db.refresh(p)
        return p
    p.status = "completed"
    db.commit()
    db.refresh(p)
    return p


def advance(db: Session, task: Task, starter: Any) -> None:
    """A task finished: if it is a running pipeline step, move the pipeline on."""
    step = db.scalars(select(PipelineStep).where(PipelineStep.task_id == task.id)).first()
    if step is None or step.status != "running":
        return
    accepted = task.status == "COMPLETED"
    # claim the transition exactly once, even if the hook fires twice
    claimed = db.execute(
        update(PipelineStep)
        .where(PipelineStep.id == step.id, PipelineStep.status == "running")
        .values(status="accepted" if accepted else "failed")
    ).rowcount
    db.commit()
    if not claimed:
        return
    db.refresh(step)
    p = db.get(Pipeline, step.pipeline_id)
    if p is None:
        return
    db.refresh(p)
    owner = p.created_by
    if not accepted:
        p.status = "paused"
        db.commit()
        notification_service.notify_safely(
            db, p.org_id, "pipeline.paused",
            f"Pipeline “{p.name}” paused: step {step.position + 1} was not accepted",
            {"pipeline_id": str(p.id), "task_id": str(task.id), "status": task.status},
            user_ids=[owner], dedupe_key=f"pipeline:{p.id}:{step.id}:paused",
        )  # fmt: skip
        return
    nxt = next((s for s in p.steps if s.position == step.position + 1), None)
    if nxt is None:
        p.status = "completed"
        db.commit()
        notification_service.notify_safely(
            db, p.org_id, "pipeline.completed",
            f"Pipeline “{p.name}” finished: every step accepted",
            {"pipeline_id": str(p.id)}, user_ids=[owner], dedupe_key=f"pipeline:{p.id}:done",
        )  # fmt: skip
        return
    if p.status != "running":
        return  # paused by a person: leave the next step for `resume`
    try:
        _launch(db, p, nxt, task, owner, starter)
    except Exception as exc:  # never break the terminal hook
        log.exception("pipeline %s could not start step %s", p.id, nxt.position)
        db.rollback()
        p.status = "paused"
        db.commit()
        notification_service.notify_safely(
            db, p.org_id, "pipeline.paused",
            f"Pipeline “{p.name}” paused: the next step could not start",
            {"pipeline_id": str(p.id), "error": str(exc)[:200]}, user_ids=[owner],
            dedupe_key=f"pipeline:{p.id}:{nxt.id}:start",
        )  # fmt: skip


def default_starter(factory: sessionmaker[Session]) -> Any:
    """How the terminal hook starts the next step: a worker job (queue) or a thread (inline)."""

    def start(task_id: uuid.UUID) -> None:
        if settings.run_mode == "queue":
            from app.services import job_service

            with factory() as db:
                job_service.enqueue(db, task_id, "start", None)
            return
        from app.execution.sandbox import get_sandbox_backend
        from app.services import run_service
        from app.services.llm_client import get_llm_client

        run_service.dispatch(
            intel_service.ThreadBackground(), factory, "start", task_id,
            get_llm_client(), get_sandbox_backend(),
        )  # fmt: skip

    return start
