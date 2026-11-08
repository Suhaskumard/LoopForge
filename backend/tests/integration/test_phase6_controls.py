"""Phase 6: per-task budgets, human approval gates, ablation switches, secret redaction."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_sandbox
from app.config import settings
from app.database.models import AgentRun, AuditEvent, Task
from app.demo.employee_management import passing_report_for_demo
from app.execution.fake_sandbox import ScriptedSandbox
from app.main import app
from app.orchestrator.loop_config import PRESETS
from app.services import run_service
from tests.conftest import register_and_login
from tests.integration.test_phase2_flow import _task
from tests.integration.test_phase4_loop import (
    HAPPY_LLM,
    failing,
    failing_update_report,
    new_task,
    run,
)

API = "/api/v1"
PLAN, BUILD, REPAIR, REVIEW = HAPPY_LLM
FAIL_THEN_PASS = [failing_update_report(), passing_report_for_demo()]


def status_of(client, h, tid):
    return client.get(f"{API}/tasks/{tid}", headers=h).json()["status"]


def events(client, h, tid):
    return [e["event_type"] for e in client.get(f"{API}/tasks/{tid}/events", headers=h).json()]


def approvals(client, h, tid):
    return client.get(f"{API}/tasks/{tid}/approvals", headers=h).json()


# ---- budgets -----------------------------------------------------------------------------


def test_task_budget_cannot_exceed_the_server_limit(client):
    h = register_and_login(client, "b@x.com")
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    body = {"project_id": p["id"], "requirement": "x"}
    over = {**body, "token_budget": settings.max_token_budget + 1}
    assert client.post(f"{API}/tasks", json=over, headers=h).status_code == 422
    assert (
        client.post(f"{API}/tasks", json={**body, "token_budget": 999}, headers=h).status_code
        == 422
    )
    ok = {**body, "token_budget": 5000, "max_cost": 0.5}
    r = client.post(f"{API}/tasks", json=ok, headers=h)
    assert r.status_code == 201
    assert (r.json()["token_budget"], r.json()["max_cost"]) == (5000, 0.5)


def test_tiny_task_budget_escalates_instead_of_spending_more(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM, token_budget=1000)
    assert status_of(client, h, tid) == "ESCALATED"


def test_cost_cap_escalates(client, monkeypatch):
    monkeypatch.setattr(settings, "cost_per_1k_tokens", 1000.0)  # every token is expensive
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM, max_cost=0.5)
    assert status_of(client, h, tid) == "ESCALATED"


# ---- approval gates ----------------------------------------------------------------------


def test_plan_approval_pauses_then_approval_resumes_to_completion(client):
    h, tid, sandbox = run(client, FAIL_THEN_PASS, HAPPY_LLM, require_plan_approval=True)
    assert status_of(client, h, tid) == "AWAITING_APPROVAL"
    (req,) = approvals(client, h, tid)
    assert req["kind"] == "plan" and req["status"] == "pending"
    assert sandbox.pytest_runs == 0  # nothing was executed before the human said yes
    assert "run_paused" in events(client, h, tid)

    r = client.post(f"{API}/tasks/{tid}/approvals/{req['id']}/approve", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert status_of(client, h, tid) == "COMPLETED"
    assert sandbox.pytest_runs == 2
    kinds = events(client, h, tid)
    assert "approval_requested" in kinds and "approval_decided" in kinds
    assert [a["status"] for a in approvals(client, h, tid)] == ["approved"]


def test_rejecting_the_plan_escalates_and_nothing_runs(client):
    h, tid, sandbox = run(
        client, [passing_report_for_demo()], HAPPY_LLM, require_plan_approval=True
    )
    (req,) = approvals(client, h, tid)
    r = client.post(f"{API}/tasks/{tid}/approvals/{req['id']}/reject", headers=h)
    assert r.status_code == 200
    assert status_of(client, h, tid) == "ESCALATED"
    assert sandbox.pytest_runs == 0
    assert approvals(client, h, tid)[0]["status"] == "rejected"


def test_a_decision_can_only_be_made_once(client):
    h, tid, _ = run(client, [passing_report_for_demo()], HAPPY_LLM, require_plan_approval=True)
    (req,) = approvals(client, h, tid)
    url = f"{API}/tasks/{tid}/approvals/{req['id']}"
    assert client.post(f"{url}/reject", headers=h).status_code == 200
    assert client.post(f"{url}/approve", headers=h).status_code == 409
    assert client.post(f"{url}/reject", headers=h).status_code == 409


def test_other_users_cannot_decide_or_list_approvals(client):
    h, tid, _ = run(client, [passing_report_for_demo()], HAPPY_LLM, require_plan_approval=True)
    (req,) = approvals(client, h, tid)
    other = register_and_login(client, "mallory@x.com")
    assert client.get(f"{API}/tasks/{tid}/approvals", headers=other).status_code == 404
    url = f"{API}/tasks/{tid}/approvals/{req['id']}/approve"
    assert client.post(url, headers=other).status_code == 404
    assert status_of(client, h, tid) == "AWAITING_APPROVAL"


def test_cancelling_a_waiting_task_ends_it_and_blocks_approval(client):
    h, tid, _ = run(client, [passing_report_for_demo()], HAPPY_LLM, require_plan_approval=True)
    (req,) = approvals(client, h, tid)
    assert client.post(f"{API}/tasks/{tid}/cancel", headers=h).status_code == 200
    url = f"{API}/tasks/{tid}/approvals/{req['id']}/approve"
    assert client.post(url, headers=h).status_code == 409


def test_waiting_tasks_are_not_treated_as_interrupted_work(client):
    run(client, [passing_report_for_demo()], HAPPY_LLM, require_plan_approval=True)
    with Session(client.engine) as s:
        assert run_service.interrupted_task_ids(s) == []


def test_a_large_repair_waits_for_approval(client, monkeypatch):
    monkeypatch.setattr(settings, "approval_max_repair_files", 0)  # any repair is "large"
    h, tid, sandbox = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    assert status_of(client, h, tid) == "AWAITING_APPROVAL"
    (req,) = approvals(client, h, tid)
    assert req["kind"] == "large_repair" and req["iteration_number"] == 2
    assert req["detail"]["files"] == ["app/routes.py"]
    assert sandbox.pytest_runs == 1  # the fix was NOT tested before approval
    client.post(f"{API}/tasks/{tid}/approvals/{req['id']}/approve", headers=h)
    assert status_of(client, h, tid) == "COMPLETED"
    assert sandbox.pytest_runs == 2


def test_small_repairs_need_no_approval(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    assert status_of(client, h, tid) == "COMPLETED" and approvals(client, h, tid) == []


# ---- experiment / ablation switches ------------------------------------------------------


def run_with(client, config, script, llm_items, email="cfg@x.com"):
    sandbox = ScriptedSandbox(script)
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(*llm_items)
    h, tid = new_task(client, email)
    with client.factory() as db:
        run_service.prepare_start(db, db.get(Task, uuid.UUID(tid)))
    run_service.execute_run(client.factory, uuid.UUID(tid), client.llm, sandbox, config)
    return h, tid, sandbox


def repair_memory_section(client, nth):
    prompt = [c.user for c in client.llm.calls if c.response_model == "RepairOutput"][nth]
    return prompt.split("Earlier repair attempts")[1].split("Project files")[0]


def test_e1_single_shot_stops_after_one_iteration_even_when_failing(client):
    h, tid, sandbox = run_with(client, PRESETS["E1"], [failing_update_report()], [PLAN, BUILD])
    assert status_of(client, h, tid) == "ESCALATED" and sandbox.pytest_runs == 1


def test_e2_allows_exactly_one_correction_cycle(client):
    h, tid, sandbox = run_with(client, PRESETS["E2"], FAIL_THEN_PASS, HAPPY_LLM)
    assert status_of(client, h, tid) == "COMPLETED" and sandbox.pytest_runs == 2


def test_a1_without_reviewer_never_calls_the_review_llm(client):
    h, tid, _ = run_with(client, PRESETS["A1"], FAIL_THEN_PASS, [PLAN, BUILD, REPAIR])
    assert status_of(client, h, tid) == "COMPLETED"
    assert "ReviewOutput" not in [c.response_model for c in client.llm.calls]


def test_a2_memory_ablation_withholds_earlier_repair_attempts(client):
    script = [failing("test_a"), failing("test_b"), passing_report_for_demo()]
    run_with(client, PRESETS["A2"], script, [PLAN, BUILD, REPAIR, REPAIR, REVIEW])
    assert "none" in repair_memory_section(client, 1)


def test_e3_includes_earlier_repair_attempts_by_default(client):
    script = [failing("test_a"), failing("test_b"), passing_report_for_demo()]
    run_with(client, PRESETS["E3"], script, [PLAN, BUILD, REPAIR, REPAIR, REVIEW])
    assert "attempt:" in repair_memory_section(client, 1)


def test_a3_without_requirement_verification_accepts_unverified_requirements(client):
    h, tid, _ = run_with(client, PRESETS["A3"], FAIL_THEN_PASS, HAPPY_LLM)
    assert status_of(client, h, tid) == "COMPLETED"


def test_a4_blind_retry_ignores_repeated_identical_failures(client):
    script = [failing("test_same")]
    llm = [PLAN, BUILD, REPAIR, REPAIR, REPAIR, REPAIR]
    _, _, blind = run_with(client, PRESETS["A4"], script, llm)
    assert blind.pytest_runs == 5  # used the whole iteration budget
    _, _, adaptive = run_with(client, PRESETS["E3"], script, llm, email="e3@x.com")
    assert adaptive.pytest_runs < 5  # fingerprinting escalated early


def test_presets_cover_the_spec_configurations():
    spec = {"E1", "E2", "E3", "A1", "A2", "A3", "A4"}
    assert spec <= set(PRESETS)  # Phase 9 adds the P0-P4 ablation presets on top
    assert set(PRESETS) - spec == {"P0", "P1", "P2", "P3", "P4"}
    assert PRESETS["E1"].max_iterations == 1 and PRESETS["E2"].max_iterations == 2
    assert PRESETS["E3"].max_iterations is None


# ---- secret redaction end to end ---------------------------------------------------------


def test_secrets_in_requirement_never_reach_the_model_or_the_database(client):
    secret = "sk-proj-abcdefghijklmnopqrstuvwx1234"
    sandbox = ScriptedSandbox([passing_report_for_demo()])
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(*HAPPY_LLM)
    h = register_and_login(client, "leak@x.com")
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    body = {"project_id": p["id"], "requirement": f"Build an API. My key is {secret}"}
    tid = client.post(f"{API}/tasks", json=body, headers=h).json()["id"]
    client.post(f"{API}/tasks/{tid}/start", headers=h)
    assert client.llm.calls and all(secret not in c.user for c in client.llm.calls)
    with Session(client.engine) as s:
        for row in s.scalars(select(AgentRun)):
            assert secret not in (row.input_summary + (row.error_message or ""))
        for ev in s.scalars(select(AuditEvent)):
            assert secret not in str(ev.event_data)
    assert _task(client, h, tid)["status"] in {"COMPLETED", "ESCALATED", "FAILED"}


def test_execution_logs_are_redacted_before_storage(client):
    secret = "ghp_" + "a1B2c3D4e5" * 4
    sandbox = ScriptedSandbox(
        [passing_report_for_demo()], stdout=f"collected tests\nGITHUB_TOKEN={secret}\n"
    )
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(*HAPPY_LLM)
    h, tid = new_task(client, "log@x.com")
    client.post(f"{API}/tasks/{tid}/start", headers=h)
    logs = client.get(f"{API}/tasks/{tid}/iterations/1/logs", headers=h).json()
    assert logs and all(secret not in entry["content"] for entry in logs)
    assert any("[REDACTED]" in entry["content"] for entry in logs)
