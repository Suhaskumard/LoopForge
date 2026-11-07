"""The event vocabulary (spec §8.2) derived from rows, without a database."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from app.services.event_stream import build_events

T0 = datetime(2026, 1, 1, 12, 0, 0)
TASK = uuid.uuid4()


def audit(kind, data=None, secs=0):
    return SimpleNamespace(
        id=uuid.uuid4(),
        event_type=kind,
        event_data=data or {},
        created_at=T0 + timedelta(seconds=secs),
    )


def run(agent, status="success", secs=0, duration=1.0):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_name=agent,
        status=status,
        started_at=T0 + timedelta(seconds=secs),
        tokens_used=10,
        duration_seconds=duration,
    )


def names(events):
    return [e["event"] for e in events]


def test_each_audit_type_maps_to_one_spec_event():
    audits = [
        audit("task_created", secs=0),
        audit("run_started", secs=1),
        audit("tests_executed", {"iteration": 1, "passed": 3, "failed": 1}, secs=2),
        audit("decision", {"iteration": 1, "action": "retry", "passed": 3, "failed": 1}, secs=3),
        audit("repair_applied", {"to_iteration": 2, "files": ["a.py"]}, secs=4),
        audit("status_changed", {"from": "REVIEWING", "to": "COMPLETED"}, secs=5),
    ]
    events = build_events(TASK, audits, [])
    assert names(events) == [
        "task_started",
        "tests_completed",
        "iteration_completed",
        "retry_scheduled",
        "task_completed",
    ]
    assert events[2]["status"] == "failed" and events[3]["iteration"] == 2


def test_terminal_status_changes():
    for target, event in (
        ("COMPLETED", "task_completed"),
        ("CANCELLED", "task_cancelled"),
        ("ESCALATED", "escalated"),
        ("FAILED", "task_failed"),
    ):
        events = build_events(TASK, [audit("status_changed", {"to": target})], [])
        assert names(events) == [event]
    # intermediate transitions are not events
    assert build_events(TASK, [audit("status_changed", {"to": "TESTING"})], []) == []


def test_decision_actions_map_to_iteration_status():
    for action, status in (("complete", "passed"), ("retry", "failed"), ("escalate", "escalated")):
        (e,) = build_events(TASK, [audit("decision", {"iteration": 1, "action": action})], [])
        assert e["status"] == status


def test_verifier_run_also_emits_sandbox_started():
    events = build_events(TASK, [], [(run("Verifier"), 1), (run("Planner", secs=-5), 1)])
    assert names(events) == [
        "agent_started",
        "agent_completed",
        "agent_started",
        "sandbox_started",
        "agent_completed",
    ]


def test_running_agent_has_started_but_not_completed():
    events = build_events(TASK, [], [(run("Builder", status="running"), 1)])
    assert names(events) == ["agent_started"]


def test_completed_event_carries_status_tokens_and_is_timed_after_start():
    r = run("Reviewer", status="failed", duration=4.0)
    events = build_events(TASK, [], [(r, 2)])
    started, finished = events
    assert (
        finished["status"] == "failed" and finished["tokens"] == 10 and finished["iteration"] == 2
    )
    assert finished["timestamp"] > started["timestamp"]


@given(st.lists(st.integers(min_value=0, max_value=50), min_size=0, max_size=12))
def test_events_are_sorted_and_ids_unique(offsets):
    runs = [(run(f"A{i}", secs=o, duration=float(i % 3)), 1) for i, o in enumerate(offsets)]
    events = build_events(TASK, [], runs)
    stamps = [e["timestamp"] for e in events]
    assert stamps == sorted(stamps)
    assert len({e["id"] for e in events}) == len(events)


def test_terminal_event_sorts_after_the_verdict_of_its_own_run_only():
    # COMPLETED is recorded a hair *before* the verdict; the viewer must still read it last.
    # A later retry run (new task_started) keeps its own, later events after it.
    audits = [
        audit("run_started", secs=0),
        audit("status_changed", {"to": "FAILED"}, secs=5),
        audit("decision", {"iteration": 1, "action": "escalate"}, secs=6),
        audit("run_started", secs=20),
        audit("decision", {"iteration": 2, "action": "complete"}, secs=30),
        audit("status_changed", {"to": "COMPLETED"}, secs=29),
    ]
    assert names(build_events(TASK, audits, [])) == [
        "task_started",
        "iteration_completed",
        "task_failed",
        "task_started",
        "iteration_completed",
        "task_completed",
    ]
