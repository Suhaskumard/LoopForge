"""Drives a task through the feedback loop and owns its run lifecycle.

`execute_run` starts a run, `resume_run` continues an interrupted one from its LangGraph
checkpoint. Failure handling is deterministic: an agent/infrastructure failure moves the task to
FAILED (or ESCALATED when a hard budget stopped it) and records an audit event. The graph itself
moves the task to COMPLETED / ESCALATED / CANCELLED when the Decision Engine says so.
"""

import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import AgentContext
from app.config import settings
from app.database.models import AuditEvent, Iteration, Task
from app.execution.sandbox import Sandbox
from app.orchestrator.checkpoint import get_checkpointer
from app.orchestrator.graph import build_graph
from app.orchestrator.state import LoopForgeState
from app.services import task_service
from app.services.llm_client import LLMClient
from app.services.task_service import TaskStatus
from app.utils.token_tracker import TokenTracker

log = logging.getLogger("loopforge.run")

# Task ids with a run active in THIS process: prevents two workers driving one task at once.
_active: set[uuid.UUID] = set()
_active_lock = threading.Lock()


class NotStartable(Exception):
    pass


class NotResumable(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def prepare_start(db: Session, task: Task) -> Task:
    """Synchronous part of /start: guard the state and move PENDING -> PLANNING."""
    if task.status != TaskStatus.PENDING.value:
        raise NotStartable(f"task is {task.status}; only PENDING tasks can be started")
    return task_service.transition(db, task, TaskStatus.PLANNING)


def prepare_retry(db: Session, task: Task) -> Task:
    """FAILED / ESCALATED -> PENDING (a fresh run with its own iteration budget)."""
    if TaskStatus(task.status) not in task_service.RETRYABLE_STATES:
        raise NotStartable(f"task is {task.status}; only FAILED or ESCALATED tasks can be retried")
    return task_service.transition(db, task, TaskStatus.PENDING)


def _initial_state(task: Task, iteration: Iteration) -> LoopForgeState:
    return LoopForgeState(
        task_id=str(task.id),
        user_requirement=task.requirement,
        project_plan={},
        generated_files={},
        test_results={},
        review_results={},
        failure_analysis=None,
        failure_fingerprints=[],
        iteration=iteration.iteration_number,
        max_iterations=task.max_iterations,
        tokens_used=0,
        started_at=time.time(),
        execution_history=[],
        quality_score=0.0,
        status="planning",
        final_report=None,
        error=None,
        escalate=False,
        iteration_in_run=1,
        best_test_count=0,
        decision=None,
        quality={},
        failure_report={},
    )


def _audit(db: Session, task: Task, event_type: str, data: dict[str, object]) -> None:
    db.add(AuditEvent(task_id=task.id, event_type=event_type, event_data=data))
    db.commit()


def _abort(db: Session, task: Task, *, escalate: bool, reason: str) -> None:
    db.refresh(task)
    target = TaskStatus.ESCALATED if escalate else TaskStatus.FAILED
    if task_service.can_transition(TaskStatus(task.status), target):
        task_service.transition(db, task, target)
    _audit(db, task, "run_failed", {"reason": reason[:1000], "escalated": escalate})


def _latest_iteration(db: Session, task: Task) -> Iteration:
    it = db.scalars(
        select(Iteration)
        .where(Iteration.task_id == task.id)
        .order_by(Iteration.iteration_number.desc())
    ).first()
    assert it is not None
    return it


def _thread_id(db: Session, task: Task) -> str | None:
    ev = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.task_id == task.id, AuditEvent.event_type == "run_started")
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
    ).first()
    return str(ev.event_data["thread_id"]) if ev else None


def _claim(task_id: uuid.UUID) -> bool:
    with _active_lock:
        if task_id in _active:
            return False
        _active.add(task_id)
        return True


def _release(task_id: uuid.UUID) -> None:
    with _active_lock:
        _active.discard(task_id)


def _drive(
    db: Session,
    task: Task,
    llm: LLMClient,
    sandbox: Sandbox,
    thread_id: str,
    graph_input: LoopForgeState | None,
    tokens_used: int,
) -> None:
    ctx = AgentContext(
        db=db,
        task=task,
        iteration=_latest_iteration(db, task),
        llm=llm,
        tracker=TokenTracker(settings.max_token_budget, used=tokens_used),
    )
    try:
        final: dict[str, Any] = build_graph(ctx, sandbox).invoke(
            graph_input, config={"configurable": {"thread_id": thread_id}}
        )
    except Exception as exc:  # a bug or infrastructure failure must not strand the task
        log.exception("run crashed for task %s", task.id)
        db.rollback()
        it = _latest_iteration(db, task)
        it.status = "failed"
        it.completed_at = _now()
        it.feedback = {**it.feedback, "error": f"{type(exc).__name__}"}
        db.commit()
        _abort(db, task, escalate=False, reason=f"internal error: {type(exc).__name__}")
        return

    it = _latest_iteration(db, task)
    it.feedback = {
        **it.feedback,
        "history": final["execution_history"],
        "tokens_used": final["tokens_used"],
    }
    if final["error"]:
        it.status = "escalated" if final["escalate"] else "failed"
        it.completed_at = _now()
        db.commit()
        _abort(db, task, escalate=final["escalate"], reason=final["error"])
        return
    db.commit()
    _audit(
        db,
        task,
        "run_finished",
        {"decision": final.get("decision"), "report": final.get("final_report") or {}},
    )


def execute_run(
    session_factory: sessionmaker[Session], task_id: Any, llm: LLMClient, sandbox: Sandbox
) -> None:
    """Background body of /start. Opens its own session; never raises."""
    if not _claim(task_id):
        log.warning("run for task %s already active; ignoring", task_id)
        return
    try:
        with session_factory() as db:
            task = db.get(Task, task_id)
            if task is None:
                log.error("execute_run: task %s vanished", task_id)
                return
            iteration = Iteration(
                task_id=task.id, iteration_number=task.current_iteration + 1, status="running"
            )
            task.current_iteration = iteration.iteration_number
            db.add(iteration)
            db.commit()
            thread_id = f"{task.id}:{uuid.uuid4().hex[:8]}"
            _audit(db, task, "run_started", {"thread_id": thread_id})
            _drive(db, task, llm, sandbox, thread_id, _initial_state(task, iteration), 0)
    finally:
        _release(task_id)


def resume_run(
    session_factory: sessionmaker[Session], task_id: Any, llm: LLMClient, sandbox: Sandbox
) -> bool:
    """Continue an interrupted run from its last checkpoint. Returns False if nothing to resume."""
    if not _claim(task_id):
        return False
    try:
        with session_factory() as db:
            task = db.get(Task, task_id)
            if task is None or TaskStatus(task.status) in (
                TaskStatus.PENDING,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.ESCALATED,
                TaskStatus.CANCELLED,
            ):
                return False
            thread_id = _thread_id(db, task)
            if thread_id is None:
                return False
            saver = get_checkpointer(db.get_bind().engine.url)
            saved = saver.get_tuple({"configurable": {"thread_id": thread_id}})
            if saved is None:
                return False
            tokens = int(saved.checkpoint["channel_values"].get("tokens_used", 0))
            _audit(db, task, "run_resumed", {"thread_id": thread_id})
            _drive(db, task, llm, sandbox, thread_id, None, tokens)
            return True
    finally:
        _release(task_id)


def interrupted_task_ids(db: Session) -> list[uuid.UUID]:
    """Tasks that were mid-run (non-terminal, started) - candidates for resume on startup."""
    active = [s.value for s in TaskStatus if s not in (
        TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.FAILED,
        TaskStatus.ESCALATED, TaskStatus.CANCELLED,
    )]  # fmt: skip
    return list(db.scalars(select(Task.id).where(Task.status.in_(active))))


def total_tokens(db: Session, task: Task) -> int:
    from app.database.models import AgentRun

    return int(
        db.scalar(
            select(func.coalesce(func.sum(AgentRun.tokens_used), 0))
            .join(Iteration, AgentRun.iteration_id == Iteration.id)
            .where(Iteration.task_id == task.id)
        )
        or 0
    )
