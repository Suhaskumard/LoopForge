"""Drives a task through the Phase 2 workflow and owns its status lifecycle.

Failure handling is deterministic: an agent failure moves the task to FAILED (or ESCALATED when a
hard budget stopped it) and records an audit event. A task is never left half-way in PLANNING.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.agents.base import AgentContext
from app.config import settings
from app.database.models import AuditEvent, Iteration, Task
from app.orchestrator.graph import build_graph
from app.orchestrator.state import LoopForgeState
from app.services import task_service
from app.services.llm_client import LLMClient
from app.services.task_service import TaskStatus
from app.utils.token_tracker import TokenTracker

log = logging.getLogger("loopforge.run")


class NotStartable(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def prepare_start(db: Session, task: Task) -> Task:
    """Synchronous part of /start: guard the state and move PENDING -> PLANNING."""
    if task.status != TaskStatus.PENDING.value:
        raise NotStartable(f"task is {task.status}; only PENDING tasks can be started")
    return task_service.transition(db, task, TaskStatus.PLANNING)


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
    )


def _audit(db: Session, task: Task, event_type: str, data: dict[str, object]) -> None:
    db.add(AuditEvent(task_id=task.id, event_type=event_type, event_data=data))
    db.commit()


def _abort(db: Session, task: Task, *, escalate: bool, reason: str) -> None:
    target = TaskStatus.ESCALATED if escalate else TaskStatus.FAILED
    if task_service.can_transition(TaskStatus(task.status), target):
        task_service.transition(db, task, target)
    _audit(db, task, "run_failed", {"reason": reason[:1000], "escalated": escalate})


def execute_run(session_factory: sessionmaker[Session], task_id: object, llm: LLMClient) -> None:
    """Background body of /start. Opens its own session; never raises."""
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
        tracker = TokenTracker(settings.max_token_budget)
        ctx = AgentContext(db=db, task=task, iteration=iteration, llm=llm, tracker=tracker)
        try:
            final = build_graph(ctx).invoke(
                _initial_state(task, iteration),
                config={"configurable": {"thread_id": str(task.id)}},
            )
        except Exception as exc:  # a bug or infrastructure failure must not strand the task
            log.exception("run crashed for task %s", task.id)
            iteration.status = "failed"
            iteration.completed_at = _now()
            iteration.feedback = {**iteration.feedback, "error": f"{type(exc).__name__}"}
            db.commit()
            _abort(db, task, escalate=False, reason=f"internal error: {type(exc).__name__}")
            return

        iteration.completed_at = _now()
        iteration.feedback = {
            **iteration.feedback,
            "history": final["execution_history"],
            "tokens_used": final["tokens_used"],
        }
        if final["error"]:
            iteration.status = "escalated" if final["escalate"] else "failed"
            db.commit()
            _abort(db, task, escalate=final["escalate"], reason=final["error"])
            return
        iteration.status = "generated"
        db.commit()
        _audit(db, task, "files_generated", {"count": len(final["generated_files"])})
