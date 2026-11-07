"""Phase 4 exit gate (Milestone 1): the autonomous feedback loop, end to end through the API.

Sandbox results come from a ScriptedSandbox and model output from the FakeLLMClient, so every
scenario is deterministic and needs neither Docker nor an API key.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_sandbox
from app.config import settings
from app.database.models import RepairHistory, Requirement, Task
from app.demo.employee_management import (
    defective_builder_output,
    demo_plan,
    failing_update_report,
    passing_report_for_demo,
    repair_output,
    review_output,
)
from app.execution.fake_sandbox import FakeSandbox, ScriptedSandbox
from app.main import app
from app.services import run_service, workspace
from tests.conftest import register_and_login
from tests.integration.test_phase2_flow import _events, _task


class Crash(BaseException):
    """Simulates the process dying mid-iteration (not an Exception, so nothing catches it)."""


def failing(name: str):
    """A failing pytest report whose single failure is called `name` (distinct fingerprint)."""
    r = failing_update_report()
    r["tests"][1]["nodeid"] = f"tests/test_routes.py::{name}"
    return r


def new_task(client, email="loop@x.com", **extra):
    h = register_and_login(client, email)
    p = client.post("/api/v1/projects", json={"name": "employee_management"}, headers=h).json()
    body = {"project_id": p["id"], "requirement": "Build an employee management API", **extra}
    return h, client.post("/api/v1/tasks", json=body, headers=h).json()["id"]


def run(client, script, llm_items, *, email="loop@x.com", **extra):
    sandbox = ScriptedSandbox(script)
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(*llm_items)
    h, tid = new_task(client, email, **extra)
    assert client.post(f"/api/v1/tasks/{tid}/start", headers=h).status_code == 202
    return h, tid, sandbox


PLAN = demo_plan()
DEFECTIVE = defective_builder_output()
HAPPY_LLM = [PLAN, DEFECTIVE, repair_output(), review_output()]


def iterations(client, h, tid):
    return client.get(f"/api/v1/tasks/{tid}/iterations", headers=h).json()


# ---- gate 1 + 2: injected defect is repaired, every repair is followed by a full re-run --------


def test_injected_defect_fails_is_repaired_and_passes_without_human_input(client):
    h, tid, sandbox = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM)
    assert _task(client, h, tid)["status"] == "COMPLETED"

    its = iterations(client, h, tid)
    assert [i["number"] for i in its] == [1, 2]
    assert its[0]["status"] == "failed_tests" and its[0]["tests"]["failed"] == 1
    assert its[1]["status"] == "accepted" and its[1]["tests"]["failed"] == 0
    assert its[1]["repair"]["files_modified"] == ["app/routes.py"]
    assert "employee_id + 1" in its[1]["repair"]["root_cause"]

    # the repaired code on disk is really the corrected version
    src = workspace.iteration_dir(its[0]["task_id"], 2)
    assert "employee_id + 1" not in (src / "app" / "routes.py").read_text(encoding="utf-8")
    old = workspace.iteration_dir(its[0]["task_id"], 1)
    assert "employee_id + 1" in (old / "app" / "routes.py").read_text(encoding="utf-8")

    with Session(client.engine) as s:
        rec = s.scalars(select(RepairHistory)).one()
        assert rec.outcome == "resolved" and rec.regression_status == "full suite re-run"
        reqs = s.scalars(select(Requirement)).all()
        assert reqs and all(r.verification_status == "verified" for r in reqs)


def test_every_repair_is_followed_by_a_full_test_rerun_before_acceptance(client):
    h, tid, sandbox = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM)
    # pytest ran once per iteration, each time on that iteration's own full workspace
    assert sandbox.pytest_runs == 2
    assert [w.name for w in sandbox.workspaces] == ["iter_1", "iter_2"]
    assert all(w.parent.name == tid for w in sandbox.workspaces)

    ev = _events(client, h, tid)
    kinds = [e["event_type"] for e in ev]
    repaired = kinds.index("repair_applied")
    completed = [i for i, e in enumerate(ev) if e["event_type"] == "decision"][-1]
    tested_between = [e for e in ev[repaired:completed] if e["event_type"] == "tests_executed"]
    assert len(tested_between) == 1 and tested_between[0]["event_data"]["iteration"] == 2
    assert ev[completed]["event_data"]["action"] == "complete"
    transitions = [
        (e["event_data"]["from"], e["event_data"]["to"])
        for e in ev
        if e["event_type"] == "status_changed"
    ]
    assert ("REVIEWING", "REPAIRING") in transitions and ("REPAIRING", "EXECUTING") in transitions
    assert transitions[-1] == ("REVIEWING", "COMPLETED")


def test_reviewer_is_not_consulted_while_tests_fail(client):
    h, tid, _ = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM)
    calls = [c.response_model for c in client.llm.calls]
    assert calls == ["ProjectPlan", "BuilderOutput", "RepairOutput", "ReviewOutput"]


# ---- gate 3: limits ----------------------------------------------------------------------


def test_iteration_limit_escalates(client):
    h, tid, sandbox = run(
        client,
        [failing("test_a"), failing("test_b"), failing("test_c")],
        [PLAN, DEFECTIVE, repair_output()],
        max_iterations=2,
    )
    assert _task(client, h, tid)["status"] == "ESCALATED"
    assert len(iterations(client, h, tid)) == 2 and sandbox.pytest_runs == 2
    last = _events(client, h, tid)[-2:]
    assert [e["event_type"] for e in last] == ["decision", "run_finished"]
    assert last[0]["event_data"]["action"] == "escalate"


def test_time_limit_escalates(client, monkeypatch):
    monkeypatch.setattr(settings, "max_task_duration_seconds", 0)
    h, tid, sandbox = run(client, [failing_update_report()], [PLAN, DEFECTIVE])
    assert _task(client, h, tid)["status"] == "ESCALATED"
    assert sandbox.pytest_runs == 1  # stopped before spending another iteration


def test_token_limit_escalates(client, monkeypatch):
    monkeypatch.setattr(settings, "max_token_budget", 4500)
    h, tid, sandbox = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM)
    assert _task(client, h, tid)["status"] == "ESCALATED"
    reason = [e for e in _events(client, h, tid) if e["event_type"] == "run_failed"][-1]
    assert "token budget" in reason["event_data"]["reason"] and reason["event_data"]["escalated"]


# ---- gate 4: identical repeated failures -------------------------------------------------


def test_identical_repeated_failure_escalates_before_the_iteration_limit(client):
    h, tid, sandbox = run(
        client,
        [failing_update_report()],  # the same failure, every time
        [PLAN, DEFECTIVE, repair_output(), repair_output()],
    )
    assert _task(client, h, tid)["status"] == "ESCALATED"
    its = iterations(client, h, tid)
    assert len(its) == 3 < 5  # 2 repair attempts, then the engine gives up
    fps = {i["decision"]["fingerprint"] for i in its}
    assert len(fps) == 1 and its[-1]["decision"]["action"] == "escalate"


def test_repair_that_deletes_tests_cannot_pass(client):
    smaller = passing_report_for_demo()
    smaller["summary"] = {"passed": 2, "total": 2, "collected": 2}
    h, tid, _ = run(client, [failing_update_report(), smaller], HAPPY_LLM)
    assert _task(client, h, tid)["status"] == "ESCALATED"  # 2 tests < the 5 we started with


# ---- gate 5: resume from a checkpoint ----------------------------------------------------


def test_workflow_interrupted_mid_iteration_resumes_from_its_checkpoint(client):
    sandbox = ScriptedSandbox([failing_update_report(), Crash, passing_report_for_demo()])
    client.llm.queue(*HAPPY_LLM)
    h, tid = new_task(client)
    with client.factory() as db:
        run_service.prepare_start(db, db.get(Task, uuid.UUID(tid)))
    with pytest.raises(Crash):  # the "process" dies while iteration 2 is being tested
        run_service.execute_run(client.factory, uuid.UUID(tid), client.llm, sandbox)

    assert _task(client, h, tid)["status"] == "EXECUTING"  # stranded mid-iteration
    llm_calls_before = len(client.llm.calls)
    assert llm_calls_before == 3  # planner, builder, repair: all already paid for

    assert run_service.resume_run(client.factory, uuid.UUID(tid), client.llm, sandbox) is True
    assert _task(client, h, tid)["status"] == "COMPLETED"
    # nothing before the checkpoint was redone: only the review was new
    assert [c.response_model for c in client.llm.calls[llm_calls_before:]] == ["ReviewOutput"]
    assert sandbox.pytest_runs == 3  # iteration 1, the crashed attempt, the resumed attempt
    assert len(iterations(client, h, tid)) == 2
    kinds = [e["event_type"] for e in _events(client, h, tid)]
    assert kinds.count("run_started") == 1 and kinds.count("run_resumed") == 1


def test_resume_refuses_finished_or_unknown_runs(client):
    h, tid, sandbox = run(client, [passing_report_for_demo()], [PLAN, DEFECTIVE, review_output()])
    assert _task(client, h, tid)["status"] == "COMPLETED"
    assert run_service.resume_run(client.factory, uuid.UUID(tid), client.llm, sandbox) is False
    r = client.post(f"/api/v1/tasks/{tid}/resume", headers=h)
    assert r.status_code == 409


def test_resume_endpoint_continues_an_interrupted_task(client):
    sandbox = ScriptedSandbox([Crash, passing_report_for_demo()])
    client.llm.queue(PLAN, DEFECTIVE, review_output())
    h, tid = new_task(client)
    with client.factory() as db:
        run_service.prepare_start(db, db.get(Task, uuid.UUID(tid)))
    with pytest.raises(Crash):
        run_service.execute_run(client.factory, uuid.UUID(tid), client.llm, sandbox)
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    assert client.post(f"/api/v1/tasks/{tid}/resume", headers=h).status_code == 202
    assert _task(client, h, tid)["status"] == "COMPLETED"


# ---- control: cancel / retry ---------------------------------------------------------------


def test_cancel_stops_the_loop(client):
    def cancel_during_first_test_run(workspace_dir, argv):
        if argv[0] == "python":
            with client.factory() as db:
                task = db.scalars(select(Task)).one()
                from app.services import task_service

                task_service.transition(db, task, task_service.TaskStatus.CANCELLED)

    sandbox = FakeSandbox(failing_update_report(), hook=cancel_during_first_test_run)
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(PLAN, DEFECTIVE, repair_output())
    h, tid = new_task(client)
    client.post(f"/api/v1/tasks/{tid}/start", headers=h)
    assert _task(client, h, tid)["status"] == "CANCELLED"
    assert [c.response_model for c in client.llm.calls] == ["ProjectPlan", "BuilderOutput"]
    assert len(iterations(client, h, tid)) == 1


def test_cancel_endpoint_and_terminal_conflict(client):
    h, tid = new_task(client)
    assert client.post(f"/api/v1/tasks/{tid}/cancel", headers=h).json()["status"] == "CANCELLED"
    assert client.post(f"/api/v1/tasks/{tid}/cancel", headers=h).status_code == 409
    assert client.post(f"/api/v1/tasks/{tid}/retry", headers=h).status_code == 409


def test_retry_gives_an_escalated_task_a_fresh_run(client):
    h, tid, _ = run(
        client,
        [failing("test_a"), failing("test_b")],
        [PLAN, DEFECTIVE, repair_output()],
        max_iterations=2,
    )
    assert _task(client, h, tid)["status"] == "ESCALATED"
    assert client.post(f"/api/v1/tasks/{tid}/retry", headers=h).json()["status"] == "PENDING"

    app.dependency_overrides[get_sandbox] = lambda: ScriptedSandbox([passing_report_for_demo()])
    client.llm.queue(PLAN, DEFECTIVE, review_output())
    assert client.post(f"/api/v1/tasks/{tid}/start", headers=h).status_code == 202
    task = _task(client, h, tid)
    assert task["status"] == "COMPLETED" and task["current_iteration"] == 3  # history is kept
    assert [i["number"] for i in iterations(client, h, tid)] == [1, 2, 3]


# ---- iteration history API ---------------------------------------------------------------


def test_iteration_history_endpoints(client):
    h, tid, _ = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM)
    first, second = iterations(client, h, tid)

    detail = client.get(f"/api/v1/iterations/{second['id']}", headers=h).json()
    assert detail["status"] == "accepted" and detail["quality_score"] == 0.9
    assert detail["review"]["critical_issues"] == 0 and detail["quality"]["ruff"] == []
    assert detail["test_results"][0]["coverage"] == 91.5
    assert len(detail["files"]) == 10 and all(len(f["sha256"]) == 64 for f in detail["files"])
    assert [r["agent_name"] for r in detail["agent_runs"]] == ["Verifier", "Reviewer"]

    diff = client.get(f"/api/v1/iterations/{second['id']}/diff", headers=h).json()
    assert diff["against"] == 1 and [f["path"] for f in diff["files"]] == ["app/routes.py"]
    assert "-    employee = get_one(employee_id + 1)" in diff["files"][0]["diff"]

    first_diff = client.get(f"/api/v1/iterations/{first['id']}/diff", headers=h).json()
    assert first_diff["against"] is None and len(first_diff["files"]) == 10

    logs = client.get(f"/api/v1/iterations/{second['id']}/logs", headers=h).json()
    assert [entry["name"] for entry in logs] == ["pytest-stderr.txt", "pytest-stdout.txt"]


def test_iteration_endpoints_are_owner_scoped(client):
    h, tid, _ = run(client, [passing_report_for_demo()], [PLAN, DEFECTIVE, review_output()])
    it = iterations(client, h, tid)[0]
    other = register_and_login(client, "intruder4@x.com")
    for path in (f"/iterations/{it['id']}", f"/iterations/{it['id']}/diff",
                 f"/iterations/{it['id']}/logs", f"/tasks/{tid}/iterations"):  # fmt: skip
        assert client.get(f"/api/v1{path}", headers=other).status_code == 404
        assert client.get(f"/api/v1{path}").status_code == 401
    for action in ("cancel", "retry", "resume"):
        assert client.post(f"/api/v1/tasks/{tid}/{action}", headers=other).status_code == 404
    unknown = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/iterations/{unknown}", headers=h).status_code == 404
