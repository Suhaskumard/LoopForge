"""Turn database rows into the spec §8.2 real-time events.

The database is the single source of truth (ADR-0010): the WebSocket handler polls these rows
and emits only events it has not sent yet. `build_events` is a pure function so the whole
vocabulary is unit-testable, and because it is rebuilt from history a client that connects late
(or reconnects) sees every step.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import AgentRun, AuditEvent, Iteration, Project, Task

TERMINAL = {"COMPLETED", "FAILED", "ESCALATED", "CANCELLED"}

# status_changed -> terminal event name
_TERMINAL_EVENT = {
    "COMPLETED": "task_completed",
    "CANCELLED": "task_cancelled",
    "ESCALATED": "escalated",
    "FAILED": "task_failed",
}
_DECISION_STATUS = {
    "complete": "passed",
    "retry": "failed",
    "escalate": "escalated",
    "stop": "stopped",
}


def _ts(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def build_events(
    task_id: uuid.UUID,
    audits: Sequence[AuditEvent],
    runs: Sequence[tuple[AgentRun, int]],
) -> list[dict[str, Any]]:
    """All events derivable from the rows, oldest first. `runs` pairs a run with its iteration #."""
    events: list[dict[str, Any]] = []

    def add(eid: str, name: str, when: datetime | None, **fields: Any) -> None:
        events.append(
            {"id": eid, "event": name, "task_id": str(task_id), "timestamp": _ts(when), **fields}
        )

    for a in audits:
        data = a.event_data or {}
        eid = f"audit:{a.id}"
        if a.event_type == "run_started":
            add(eid, "task_started", a.created_at)
        elif a.event_type == "status_changed" and data.get("to") in _TERMINAL_EVENT:
            add(eid, _TERMINAL_EVENT[str(data["to"])], a.created_at, status=str(data["to"]).lower())
        elif a.event_type == "tests_executed":
            add(
                eid,
                "tests_completed",
                a.created_at,
                iteration=data.get("iteration"),
                tests_passed=data.get("passed", 0),
                tests_failed=data.get("failed", 0),
            )
        elif a.event_type == "decision":
            add(
                eid,
                "iteration_completed",
                a.created_at,
                iteration=data.get("iteration"),
                status=_DECISION_STATUS.get(str(data.get("action")), str(data.get("action"))),
                tests_passed=data.get("passed", 0),
                tests_failed=data.get("failed", 0),
            )
        elif a.event_type in ("approval_requested", "approval_decided"):
            add(
                eid,
                a.event_type,
                a.created_at,
                kind=data.get("kind"),
                decision=data.get("decision"),
            )
        elif a.event_type == "repair_applied":
            add(
                eid,
                "retry_scheduled",
                a.created_at,
                iteration=data.get("to_iteration"),
                files=data.get("files", []),
            )

    for run, number in runs:
        add(
            f"run-start:{run.id}",
            "agent_started",
            run.started_at,
            agent=run.agent_name,
            iteration=number,
        )
        if run.agent_name == "Verifier":
            add(f"sandbox:{run.id}", "sandbox_started", run.started_at, iteration=number)
        if run.status != "running":
            add(
                f"run-end:{run.id}",
                "agent_completed",
                run.started_at + timedelta(seconds=run.duration_seconds),
                agent=run.agent_name,
                iteration=number,
                status=run.status,
                tokens=run.tokens_used,
                duration_seconds=run.duration_seconds,
            )
    _settle_terminal_events(events)
    # Stable order: time, then start-before-end so an instant agent still reads naturally.
    rank = {"agent_started": 0, "sandbox_started": 1, "agent_completed": 2}
    rank.update({name: 4 for name in _TERMINAL_EVENT.values()})
    events.sort(key=lambda e: (e["sort"], rank.get(e["event"], 3), e["id"]))
    for e in events:
        del e["sort"]
    return events


_TERMINAL_NAMES = set(_TERMINAL_EVENT.values())


def _settle_terminal_events(events: list[dict[str, Any]]) -> None:
    """Give every event a `sort` key. The Decision Engine moves the task to its terminal state a
    few milliseconds *before* it records the iteration verdict; a viewer should still read
    "iteration completed" first, so a terminal event sorts after the verdicts of its own run."""
    starts = sorted(e["timestamp"] for e in events if e["event"] == "task_started")
    for e in events:
        e["sort"] = e["timestamp"]
    for e in events:
        if e["event"] not in _TERMINAL_NAMES:
            continue
        end = next((s for s in starts if s > e["timestamp"]), "￿")
        verdicts = [
            v["timestamp"]
            for v in events
            if v["event"] == "iteration_completed" and e["timestamp"] <= v["timestamp"] < end
        ]
        if verdicts:
            e["sort"] = max(verdicts)


def poll_task(
    factory: sessionmaker[Session], user_id: uuid.UUID, task_id: uuid.UUID
) -> tuple[str, list[dict[str, Any]]] | None:
    """Current status and full event history, or None if the task is not this user's."""
    with factory() as db:
        task = db.get(Task, task_id)
        project = db.get(Project, task.project_id) if task else None
        if task is None or project is None or project.user_id != user_id:
            return None
        audits = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.task_id == task.id)
                .order_by(AuditEvent.created_at)
            )
        )
        rows = db.execute(
            select(AgentRun, Iteration.iteration_number)
            .join(Iteration, AgentRun.iteration_id == Iteration.id)
            .where(Iteration.task_id == task.id)
        ).all()
        return task.status, build_events(task.id, audits, [(r, n) for r, n in rows])


__all__ = ["TERMINAL", "build_events", "poll_task"]
