"""Round 9: forecast, code comments read by Repair, regression watch, task chains, model A/B."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database.models import AgentRun, Notification, RegressionWatch, Task
from app.services import intel_service, workspace
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import (
    HAPPY_LLM,
    failing_update_report,
    new_task,
    passing_report_for_demo,
    run,
)

API = "/api/v1"


def completed(client, email="intel@x.com"):
    h, tid, _ = run(
        client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM, email=email
    )
    assert client.get(f"{API}/tasks/{tid}", headers=h).json()["status"] == "COMPLETED"
    return h, tid


# ---- 1. forecast ---------------------------------------------------------------------------------


def test_forecast_reflects_finished_tasks_and_stays_in_the_org(client):
    h, _ = completed(client)
    f = client.get(f"{API}/forecast", params={"language": "python", "words": 5}, headers=h).json()
    assert f["basis"] == 1 and f["scope"] == "organization"  # fewer than 3 similar: org-wide
    assert f["accept_rate"] == 1.0
    assert f["tokens"]["p50"] > 0 and f["tokens"]["p90"] >= f["tokens"]["p50"]
    assert f["iterations"] == {"p50": 2.0, "p90": 2.0}
    other = register_and_login(client, "other-org@x.com")
    empty = client.get(f"{API}/forecast", headers=other).json()
    assert empty["basis"] == 0 and empty["scope"] == "none" and empty["tokens"] is None


# ---- 2. comments reach the Repair agent ----------------------------------------------------------


def test_unresolved_code_comments_are_given_to_the_repair_agent(client):
    from app.api.dependencies import get_sandbox
    from app.execution.fake_sandbox import ScriptedSandbox
    from app.main import app

    h, tid = new_task(client, "notes@x.com")
    note = {"file_path": "app/routes.py", "line": 12, "body": "the id is off by one here"}
    r = client.post(f"{API}/tasks/{tid}/comments", json=note, headers=h)
    assert r.status_code == 201 and r.json()["author"] == "notes@x.com"
    stale = client.post(f"{API}/tasks/{tid}/comments", json={"body": "old idea"}, headers=h).json()
    patched = client.patch(
        f"{API}/tasks/{tid}/comments/{stale['id']}", json={"resolved": True}, headers=h
    )
    assert patched.json()["resolved"] is True

    sandbox = ScriptedSandbox([failing_update_report(), passing_report_for_demo()])
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(*HAPPY_LLM)
    assert client.post(f"{API}/tasks/{tid}/start", headers=h).status_code == 202

    repair = [c for c in client.llm.calls if c.response_model.startswith("Repair")]
    assert repair, "the loop should have repaired once"
    prompt = repair[0].user
    assert "Notes from human reviewers" in prompt
    assert "app/routes.py:12 — the id is off by one here" in prompt
    assert "old idea" not in prompt  # resolved notes are not sent
    listed = client.get(f"{API}/tasks/{tid}/comments", headers=h).json()
    assert [c["resolved"] for c in listed] == [False, True]
    outsider = register_and_login(client, "nosy@x.com")
    assert client.get(f"{API}/tasks/{tid}/comments", headers=outsider).status_code in (403, 404)


# ---- 3. regression watch -------------------------------------------------------------------------


def test_watch_schedules_reruns_and_alerts_on_regression(client):
    h, tid = completed(client, "watch@x.com")
    w = client.put(f"{API}/tasks/{tid}/watch", json={"interval_hours": 24}, headers=h).json()
    assert w["watch"]["interval_hours"] == 24 and w["watch"]["active"] is True

    started: list[uuid.UUID] = []
    with client.factory() as db:
        watch = db.scalars(select(RegressionWatch)).one()
        watch.next_run_at = datetime(2020, 1, 1)
        db.commit()
        now = datetime(2026, 6, 1)
        assert intel_service.run_due(db, started.append, now=now) == 1
        assert intel_service.run_due(db, started.append, now=now) == 0  # rescheduled, not due
        db.refresh(watch)
        assert watch.next_run_at == now + timedelta(hours=24)
        clone = db.get(Task, started[0])
        assert clone.rerun_of == uuid.UUID(tid) and clone.status == "PLANNING"
        assert watch.last_run_task_id == clone.id and watch.last_result == "running"

        clone.status = "FAILED"
        db.commit()
        intel_service.on_terminal(db, clone)
        db.refresh(watch)
        assert watch.last_result == "regressed"
        alerts = db.scalars(select(Notification).where(Notification.kind == "regression")).all()
        assert alerts and "Regression" in alerts[0].title

    status = client.get(f"{API}/tasks/{tid}/watch", headers=h).json()
    assert status["watch"]["last_result"] == "regressed"
    assert [r["id"] for r in status["reruns"]] == [str(started[0])]
    assert client.delete(f"{API}/tasks/{tid}/watch", headers=h).status_code == 204
    assert client.get(f"{API}/tasks/{tid}/watch", headers=h).json()["watch"] is None


def test_only_accepted_tasks_can_be_watched_or_rerun(client):
    h, tid = new_task(client, "pending@x.com")
    assert client.put(f"{API}/tasks/{tid}/watch", json={}, headers=h).status_code == 409
    assert client.post(f"{API}/tasks/{tid}/rerun", headers=h).status_code == 409


# ---- 4. task chains ------------------------------------------------------------------------------


def test_a_task_can_continue_from_another_tasks_accepted_code(client):
    h, tid = completed(client, "chain@x.com")
    pid = client.get(f"{API}/tasks/{tid}", headers=h).json()["project_id"]
    body = {"project_id": pid, "requirement": "Add pagination to the list endpoint",
            "source_type": "task", "from_task_id": tid}  # fmt: skip
    r = client.post(f"{API}/tasks", json=body, headers=h)
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["source_type"] == "task" and child["source_ref"] == tid and child["source_hash"]
    with client.factory() as db:
        expected = intel_service.accepted_files(db.get(Task, uuid.UUID(tid)), db)
    assert workspace.read_seed(uuid.UUID(child["id"])) == expected

    graph = client.get(f"{API}/graph", headers=h).json()
    assert {"source": f"t:{child['id']}", "target": f"t:{tid}", "kind": "chained_from"} in graph[
        "edges"
    ]

    _, pending = new_task(client, "chain@x.com")
    bad = {**body, "from_task_id": pending}
    assert client.post(f"{API}/tasks", json=bad, headers=h).status_code == 409
    missing = {**body, "from_task_id": str(uuid.uuid4())}
    assert client.post(f"{API}/tasks", json=missing, headers=h).status_code == 404
    no_id = {k: v for k, v in body.items() if k != "from_task_id"}
    assert client.post(f"{API}/tasks", json=no_id, headers=h).status_code == 422


# ---- 5. model A/B --------------------------------------------------------------------------------


def test_a_task_model_override_is_used_and_recorded(client):
    from app.api.dependencies import get_sandbox
    from app.execution.fake_sandbox import ScriptedSandbox
    from app.main import app

    h, tid = new_task(client, "model@x.com")
    with client.factory() as db:
        db.get(Task, uuid.UUID(tid)).model_overrides = {"Planner": "model-x"}
        db.commit()
    app.dependency_overrides[get_sandbox] = lambda: ScriptedSandbox(
        [failing_update_report(), passing_report_for_demo()]
    )
    client.llm.queue(*HAPPY_LLM)
    client.post(f"{API}/tasks/{tid}/start", headers=h)
    assert client.llm.calls[0].model == "model-x"
    with client.factory() as db:
        planner = db.scalars(select(AgentRun).where(AgentRun.agent_name == "Planner")).first()
        assert planner.model == "model-x"


def test_an_experiment_runs_two_variants_that_differ_only_in_the_model(client):
    h, tid = completed(client, "ab@x.com")
    body = {"agent": "Repair", "model_a": "model-a", "model_b": "model-b"}
    r = client.post(f"{API}/tasks/{tid}/experiments", json=body, headers=h)
    assert r.status_code == 202, r.text
    exp = r.json()
    assert len(exp["variants"]) == 2
    assert [v["model_overrides"] for v in exp["variants"]] == [
        {"Repair": "model-a"},
        {"Repair": "model-b"},
    ]
    assert {v["rerun_of"] for v in exp["variants"]} == {tid}
    again = client.get(f"{API}/experiments/{exp['experiment']}", headers=h).json()
    assert [v["task_id"] for v in again["variants"]] == [v["task_id"] for v in exp["variants"]]
    same = {**body, "model_b": "model-a"}
    assert client.post(f"{API}/tasks/{tid}/experiments", json=same, headers=h).status_code == 409
    weird = {**body, "model_a": "bad model!"}
    assert client.post(f"{API}/tasks/{tid}/experiments", json=weird, headers=h).status_code == 422
    stranger = register_and_login(client, "ab-other@x.com")
    url = f"{API}/experiments/{exp['experiment']}"
    assert client.get(url, headers=stranger).status_code == 404
