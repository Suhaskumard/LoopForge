import copy
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import AuditEvent
from app.demo.employee_management import (
    DEMO_REQUIREMENT,
    PLAN,
    builder_output,
    demo_responses,
)
from tests.conftest import register_and_login


def _setup(client, email="p2@x.com"):
    h = register_and_login(client, email)
    p = client.post("/api/v1/projects", json={"name": "employee_management"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": DEMO_REQUIREMENT},
        headers=h,
    ).json()
    return h, t


def _start(client, h, task_id, **kw):
    headers = kw.pop("headers", h)
    return client.post(f"/api/v1/tasks/{task_id}/start", headers=headers, **kw)


def _task(client, h, tid):
    return client.get(f"/api/v1/tasks/{tid}", headers=h).json()


def _events(client, h, tid):
    return client.get(f"/api/v1/tasks/{tid}/events", headers=h).json()


def _transitions(events):
    return [
        (e["event_data"]["from"], e["event_data"]["to"])
        for e in events
        if e["event_type"] == "status_changed"
    ]


# ---- the Phase 2 exit gate ----------------------------------------------------------------


def test_demo_requirement_produces_valid_plan_with_ids_and_criteria(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    r = _start(client, h, t["id"])
    assert r.status_code == 202 and r.json()["status"] == "PLANNING"
    assert r.headers["etag"]

    plan = client.get(f"/api/v1/tasks/{t['id']}/plan", headers=h).json()["plan"]
    assert plan["project_name"] == "employee_management" and plan["framework"] == "FastAPI"
    assert len(plan["acceptance_criteria"]) >= 4
    reqs = client.get(f"/api/v1/tasks/{t['id']}/requirements", headers=h).json()
    assert [r["req_id"] for r in reqs] == [f"REQ-00{i}" for i in range(1, 8)]
    assert {r["req_type"] for r in reqs} == {"security", "functional", "non_functional"}
    by_id = {r["req_id"]: r["impl_mapping"] for r in reqs}
    assert "app/routes.py" in by_id["REQ-002"] and by_id["REQ-007"] == ["tests/test_routes.py"]
    assert all(r["verification_status"] == "pending" for r in reqs)  # nothing verified yet
    done = _task(client, h, t["id"])
    assert done["acceptance_criteria"] == plan["acceptance_criteria"]


def test_builder_writes_complete_structure_into_workspace_only(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    files = client.get(f"/api/v1/tasks/{t['id']}/files", headers=h).json()
    expected = sorted(f.path for f in builder_output().files)
    assert [f["path"] for f in files] == expected
    assert all(len(f["sha256"]) == 64 and f["iteration"] == 1 for f in files)

    content = client.get(f"/api/v1/tasks/{t['id']}/files/app/routes.py", headers=h).json()
    assert content["content"].startswith("from fastapi") and content["path"] == "app/routes.py"

    from app.services import workspace

    root = workspace.workspace_root()
    on_disk = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert on_disk == sorted(f"{t['id']}/iter_1/{p}" for p in expected)  # nothing else anywhere


def test_malformed_output_is_rejected_logged_and_not_silently_accepted(client):
    h, t = _setup(client)
    bad = copy.deepcopy(PLAN)
    bad["requirements"] = []
    client.llm.queue("not json at all", bad)  # two rejections -> failure
    _start(client, h, t["id"])
    task = _task(client, h, t["id"])
    assert task["status"] == "FAILED"
    ev = _events(client, h, t["id"])
    rejected = [e for e in ev if e["event_type"] == "agent_output_rejected"]
    assert len(rejected) == 2 and rejected[0]["event_data"]["agent"] == "Planner"
    assert any(e["event_type"] == "run_failed" for e in ev)
    assert client.get(f"/api/v1/tasks/{t['id']}/requirements", headers=h).json() == []
    assert client.get(f"/api/v1/tasks/{t['id']}/files", headers=h).json() == []
    assert client.get(f"/api/v1/tasks/{t['id']}/plan", headers=h).status_code == 404


# ---- lifecycle / audit --------------------------------------------------------------------


def test_status_lifecycle_audit_trail_and_agent_runs(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    task = _task(client, h, t["id"])
    assert task["status"] == "GENERATING" and task["current_iteration"] == 1
    ev = _events(client, h, t["id"])
    assert _transitions(ev) == [("PENDING", "PLANNING"), ("PLANNING", "GENERATING")]
    assert ev[-1]["event_type"] == "files_generated" and ev[-1]["event_data"]["count"] == 10

    runs = client.get(f"/api/v1/tasks/{t['id']}/agent-runs", headers=h).json()
    assert [r["agent_name"] for r in runs] == ["Planner", "Builder"]  # chronological
    assert all(r["status"] == "success" and r["tokens_used"] > 0 for r in runs)
    assert all(r["error_message"] is None for r in runs)


def test_start_is_only_allowed_from_pending(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    assert _start(client, h, t["id"]).status_code == 202
    again = _start(client, h, t["id"])
    assert again.status_code == 409 and "GENERATING" in again.json()["error"]["message"]
    assert len(client.llm.calls) == 2  # the second start never reached the LLM


def test_start_honours_if_match(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    stale = _start(client, h, t["id"], headers={**h, "If-Match": '"99"'})
    assert stale.status_code == 412
    assert _task(client, h, t["id"])["status"] == "PENDING"
    etag = client.get(f"/api/v1/tasks/{t['id']}", headers=h).headers["etag"]
    assert _start(client, h, t["id"], headers={**h, "If-Match": etag}).status_code == 202


def test_start_requires_auth_and_ownership(client):
    h, t = _setup(client)
    other = register_and_login(client, "other@x.com")
    assert client.post(f"/api/v1/tasks/{t['id']}/start").status_code == 401
    assert _start(client, other, t["id"]).status_code == 404
    assert _start(client, h, str(uuid.uuid4())).status_code == 404
    assert client.llm.calls == []
    assert _task(client, h, t["id"])["status"] == "PENDING"


def test_inspection_endpoints_are_owner_scoped(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    other = register_and_login(client, "other@x.com")
    for path in ("plan", "requirements", "agent-runs", "files", "files/app/main.py"):
        assert client.get(f"/api/v1/tasks/{t['id']}/{path}", headers=other).status_code == 404
        assert client.get(f"/api/v1/tasks/{t['id']}/{path}").status_code == 401


# ---- failure handling ---------------------------------------------------------------------


def test_builder_failure_marks_task_failed_but_keeps_plan(client):
    h, t = _setup(client)
    wrong = builder_output().model_dump()
    wrong["files"] = wrong["files"][:3] + [wrong["files"][-1]]  # missing files twice
    client.llm.queue(demo_responses()[0], wrong, wrong)
    _start(client, h, t["id"])
    assert _task(client, h, t["id"])["status"] == "FAILED"
    assert _transitions(_events(client, h, t["id"]))[-1] == ("GENERATING", "FAILED")
    runs = client.get(f"/api/v1/tasks/{t['id']}/agent-runs", headers=h).json()
    assert [(r["agent_name"], r["status"]) for r in runs] == [
        ("Planner", "success"),
        ("Builder", "failed"),
    ]
    assert client.get(f"/api/v1/tasks/{t['id']}/files", headers=h).json() == []
    assert client.get(f"/api/v1/tasks/{t['id']}/plan", headers=h).status_code == 200


def test_token_budget_exhaustion_escalates(client, monkeypatch):
    monkeypatch.setattr(settings, "max_token_budget", 5)
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    assert _task(client, h, t["id"])["status"] == "ESCALATED"
    ev = _events(client, h, t["id"])
    failed = next(e for e in ev if e["event_type"] == "run_failed")
    assert failed["event_data"]["escalated"] is True and "budget" in failed["event_data"]["reason"]


def test_unexpected_crash_never_strands_the_task(client):
    h, t = _setup(client)
    client.llm.queue(RuntimeError("provider SDK exploded"))
    _start(client, h, t["id"])
    assert _task(client, h, t["id"])["status"] == "FAILED"
    failed = next(e for e in _events(client, h, t["id"]) if e["event_type"] == "run_failed")
    assert "internal error" in failed["event_data"]["reason"]
    assert "exploded" not in failed["event_data"]["reason"]  # no internal detail leaked


def test_llm_provider_error_fails_task(client):
    from app.services.llm_client import LLMError

    h, t = _setup(client)
    client.llm.queue(LLMError("OpenAI unavailable after retries: RateLimitError"))
    _start(client, h, t["id"])
    assert _task(client, h, t["id"])["status"] == "FAILED"


def test_missing_llm_configuration_is_503_and_task_stays_pending(client, monkeypatch):
    from app.api.dependencies import get_llm
    from app.main import app

    app.dependency_overrides.pop(get_llm)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    h, t = _setup(client)
    r = _start(client, h, t["id"])
    assert r.status_code == 503 and "OPENAI" in r.json()["error"]["message"]
    assert _task(client, h, t["id"])["status"] == "PENDING"


def test_fake_provider_serves_the_demo_end_to_end(client, monkeypatch):
    """LLM_PROVIDER=fake wires the built-in demo (used by the gate script)."""
    from app.api.dependencies import get_llm
    from app.main import app

    app.dependency_overrides.pop(get_llm)
    monkeypatch.setattr(settings, "llm_provider", "fake")
    h, t = _setup(client)
    assert _start(client, h, t["id"]).status_code == 202
    assert _task(client, h, t["id"])["status"] == "GENERATING"


# ---- files endpoint hardening -------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "app/../../x.py", "nope.py", "app", "app/"],
)
def test_file_endpoint_cannot_read_outside_generated_set(client, path):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    assert client.get(f"/api/v1/tasks/{t['id']}/files/{path}", headers=h).status_code in (404, 405)


def test_file_endpoint_ignores_files_not_recorded_as_artifacts(client):
    from app.services import workspace

    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    stray = workspace.iteration_dir(uuid.UUID(t["id"]), 1) / "planted.py"
    stray.write_text("secret = 1")
    assert client.get(f"/api/v1/tasks/{t['id']}/files/planted.py", headers=h).status_code == 404
    listed = [f["path"] for f in client.get(f"/api/v1/tasks/{t['id']}/files", headers=h).json()]
    assert "planted.py" not in listed


# ---- agents list --------------------------------------------------------------------------


def test_agents_endpoint(client):
    assert client.get("/api/v1/agents").status_code == 401
    h = register_and_login(client, "ag@x.com")
    agents = {a["name"]: a for a in client.get("/api/v1/agents", headers=h).json()}
    assert set(agents) == {"Planner", "Builder", "Verifier", "Repair", "Reviewer", "Documentation"}
    assert agents["Planner"]["implemented"] and agents["Builder"]["implemented"]
    assert not agents["Verifier"]["implemented"]
    assert agents["Planner"]["may_not"] == "Write code"


def test_audit_events_recorded_in_db(client):
    h, t = _setup(client)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    with Session(client.engine) as s:
        types = [
            e.event_type for e in s.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
        ]
    assert types[0] == "task_created" and "files_generated" in types
