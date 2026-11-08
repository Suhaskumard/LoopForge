"""Phase 10 governance: audit completeness and append-only, quotas, retention, export, deletion."""

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_sandbox
from app.database.models import (
    AgentRun,
    ApprovalRequest,
    AuditLog,
    Iteration,
    Organization,
    Task,
)
from app.execution.fake_sandbox import ScriptedSandbox
from app.main import app
from app.services import audit_service, quota_service, retention_service
from tests.integration.test_phase4_loop import (
    HAPPY_LLM,
    failing_update_report,
    passing_report_for_demo,
)
from tests.integration.test_phase10_authz import (  # noqa: F401
    API,
    _build_world,
    _fast_bcrypt,
    fresh,
)


def audit(world, **params):
    r = world["client"].get(
        f"{API}/orgs/{world['org_a']}/audit",
        params={"limit": 500, **params},
        headers=world["headers"]["admin"],
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---- audit completeness -----------------------------------------------------------------------


def test_every_sensitive_action_leaves_exactly_one_attributed_audit_row(fresh):  # noqa: F811
    client, admin, org = fresh["client"], fresh["headers"]["admin"], fresh["org_a"]
    me = client.get(f"{API}/auth/me", headers=admin).json()["id"]
    viewer_id = next(
        m["user_id"]
        for m in client.get(f"{API}/orgs/{org}/members", headers=admin).json()
        if m["email"] == "viewer_a@example.com"
    )
    url = f"{API}/orgs/{org}"
    assert client.patch(url, json={"retention_days": 30}, headers=admin).status_code == 200
    assert (
        client.patch(
            f"{url}/members/{viewer_id}", json={"role": "developer"}, headers=admin
        ).status_code
        == 200
    )
    assert client.delete(f"{url}/members/{viewer_id}", headers=admin).status_code == 204
    assert client.post(f"{API}/tasks/{fresh['task']}/cancel", headers=admin).status_code == 200
    assert client.get(f"{url}/export", headers=admin).status_code == 200
    assert client.post(f"{url}/retention/run", headers=admin).status_code == 200
    with client.factory() as db:  # a pending approval to decide
        task = db.get(Task, uuid.UUID(fresh["task"]))
        task.status = "AWAITING_APPROVAL"
        req = ApprovalRequest(
            task_id=task.id, kind="plan", status="pending", resume_status="PLANNING", summary="s"
        )
        db.add(req)
        db.commit()
        req_id = req.id
    ap = fresh["headers"]["approver"]
    assert (
        client.post(
            f"{API}/tasks/{fresh['task']}/approvals/{req_id}/reject", headers=ap
        ).status_code
        == 200
    )
    assert client.delete(f"{API}/projects/{fresh['project']}", headers=admin).status_code == 204
    assert (
        client.request(
            "DELETE", f"{url}/data", json={"confirm": "wrong"}, headers=admin
        ).status_code
        == 422
    )  # a refused deletion must not be logged as performed
    assert (
        client.request(
            "DELETE",
            f"{url}/data",
            json={"confirm": client.get(url, headers=admin).json()["slug"]},
            headers=admin,
        ).status_code
        == 200
    )

    rows = audit(fresh)
    by_action: dict[str, list[dict]] = {}
    for row in rows:
        by_action.setdefault(row["action"], []).append(row)
    expected = {
        "auth.register": me,  # the admin's own registration landed in their personal org
        "auth.login": me,
        "project.create": me,
        "task.create": me,
        "member.add": me,
        "org.update": me,
        "member.role_change": me,
        "member.remove": me,
        "task.cancel": me,
        "org.export": me,
        "org.retention_run": me,
        "project.delete": me,
        "org.delete_data": me,
    }
    for action, actor in expected.items():
        hits = [r for r in by_action.get(action, []) if r["actor_id"] == actor]
        assert hits, f"no audit row for {action}"
    assert len(by_action["org.delete_data"]) == 1
    assert len(by_action["member.remove"]) == 1 and len(by_action["org.export"]) == 1
    approval = by_action["approval.rejected"]
    assert len(approval) == 1 and approval[0]["actor_id"] != me  # attributed to the approver
    # ordered newest first, and filterable
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)
    only = audit(fresh, action="member.add")
    assert {r["action"] for r in only} == {"member.add"} and len(only) == 3


def test_the_audit_log_is_append_only_at_the_database_level(fresh):  # noqa: F811
    client = fresh["client"]
    with client.factory() as db:
        row = audit_service.record(db, org_id=None, actor_id=None, action="probe")
        row_id = row.id
    for statement in (
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
    ):
        with pytest.raises(DBAPIError):
            with client.engine.begin() as conn:
                conn.execute(text(statement))
    with client.factory() as db:
        assert db.get(AuditLog, row_id).action == "probe"  # untouched
        db.delete(db.get(AuditLog, row_id))
        with pytest.raises(DBAPIError):
            db.commit()


def test_audit_detail_is_redacted_and_pii_is_opt_in(fresh):  # noqa: F811
    client, org_id = fresh["client"], uuid.UUID(fresh["org_a"])
    secret = "sk-" + "a1b2c3d4e5f6g7h8i9j0k1l2"
    with client.factory() as db:
        audit_service.record(
            db, org_id=org_id, actor_id=None, action="probe.a",
            detail={"note": f"key {secret} for bob@example.com", "nested": ["+1 (555) 123-4567"]},
        )  # fmt: skip
        db.get(Organization, org_id).redact_pii = True
        db.commit()
        audit_service.record(
            db, org_id=org_id, actor_id=None, action="probe.b",
            detail={"note": "mail bob@example.com", "nested": ["call +1 (555) 123-4567"]},
        )  # fmt: skip
    a = audit(fresh, action="probe.a")[0]["detail"]
    assert secret not in json.dumps(a) and "bob@example.com" in a["note"]  # secrets always, PII not
    b = audit(fresh, action="probe.b")[0]["detail"]
    assert "bob@example.com" not in json.dumps(b) and "555" not in json.dumps(b)


# ---- quotas -------------------------------------------------------------------------------------


def _patch(world, **fields):
    r = world["client"].patch(
        f"{API}/orgs/{world['org_a']}", json=fields, headers=world["headers"]["admin"]
    )
    assert r.status_code == 200, r.text


def test_task_quota_blocks_creation_and_is_audited(fresh):  # noqa: F811
    client, admin = fresh["client"], fresh["headers"]["admin"]
    _patch(fresh, max_tasks_month=2)  # the world already holds one task
    body = {"project_id": fresh["project"], "requirement": "Build another small API with tests."}
    assert client.post(f"{API}/tasks", json=body, headers=admin).status_code == 201
    blocked = client.post(f"{API}/tasks", json=body, headers=admin)
    assert blocked.status_code == 429, blocked.text
    assert "task quota" in blocked.text
    assert [r["detail"]["reason"] for r in audit(fresh, action="quota.blocked")] == [
        "monthly task quota reached (2)"
    ]
    usage = client.get(f"{API}/orgs/{fresh['org_a']}/usage", headers=admin).json()
    assert usage["tasks_created"] == 2 and usage["tasks_remaining"] == 0
    _patch(fresh, max_tasks_month=None)  # a null clears the cap
    assert client.post(f"{API}/tasks", json=body, headers=admin).status_code == 201


_spent = iter(range(100, 10_000))


def _spend(client, task_id, tokens, when=None):
    with client.factory() as db:
        it = Iteration(task_id=uuid.UUID(task_id), iteration_number=next(_spent))
        db.add(it)
        db.flush()
        run = AgentRun(iteration_id=it.id, agent_name="Builder", tokens_used=tokens)
        if when:
            run.started_at = when
        db.add(run)
        db.commit()


def test_token_quota_blocks_a_run_and_only_counts_this_month(fresh):  # noqa: F811
    client, admin = fresh["client"], fresh["headers"]["admin"]
    _patch(fresh, token_quota_month=1000)
    last_month = datetime.utcnow().replace(day=1) - timedelta(days=2)
    _spend(client, fresh["task"], 5000, when=last_month)  # does not count
    usage = client.get(f"{API}/orgs/{fresh['org_a']}/usage", headers=admin).json()
    assert usage["tokens_used"] == 0 and usage["tokens_remaining"] == 1000
    _spend(client, fresh["task"], 1200)
    blocked = client.post(f"{API}/tasks/{fresh['task']}/start", headers=admin)
    assert blocked.status_code == 429 and "token quota" in blocked.text
    assert audit(fresh, action="quota.blocked")[0]["target_id"] == fresh["task"]
    other_org = client.post(
        f"{API}/orgs", json={"name": "Other"}, headers=fresh["users"]["admin_a"]
    ).json()
    assert (
        client.get(f"{API}/orgs/{other_org['id']}/usage", headers=fresh["users"]["admin_a"]).json()[
            "tokens_used"
        ]
        == 0
    )  # another organization's spend is not shared


def test_token_ceiling_is_what_is_left_for_this_task(fresh):  # noqa: F811
    client = fresh["client"]
    with client.factory() as db:
        task = db.get(Task, uuid.UUID(fresh["task"]))
        assert quota_service.token_ceiling(db, task, 0) is None  # no quota, no ceiling
        db.get(Organization, task.project.org_id).token_quota_month = 1000
        db.commit()
    _spend(client, fresh["task"], 100)  # this task has used 100 ...
    other = client.post(
        f"{API}/tasks",
        json={
            "project_id": fresh["project"],
            "requirement": "A second task that also used tokens.",
        },
        headers=fresh["headers"]["admin"],
    ).json()["id"]
    _spend(client, other, 600)  # ... and a sibling used 600
    with client.factory() as db:
        task = db.get(Task, uuid.UUID(fresh["task"]))
        assert quota_service.token_ceiling(db, task, 100) == 400  # 1000 - 600 (own 100 stays in)


def test_a_run_stops_at_the_organization_quota(fresh):  # noqa: F811
    """End to end: the loop is capped by what is left of the month and escalates."""
    client, admin = fresh["client"], fresh["headers"]["admin"]
    _patch(fresh, token_quota_month=50)  # far less than one planning call needs
    app.dependency_overrides[get_sandbox] = lambda: ScriptedSandbox(
        [failing_update_report(), passing_report_for_demo()]
    )
    client.llm.queue(*HAPPY_LLM)
    assert client.post(f"{API}/tasks/{fresh['task']}/start", headers=admin).status_code == 202
    status = client.get(f"{API}/tasks/{fresh['task']}", headers=admin).json()["status"]
    assert status in ("ESCALATED", "FAILED"), status
    assert status != "COMPLETED"


# ---- retention, export, deletion ----------------------------------------------------------------


def _task_dir(task_id):
    from app.services import workspace

    return workspace.workspace_root() / task_id


def test_retention_purges_only_old_finished_tasks_and_their_files(fresh):  # noqa: F811
    client, admin = fresh["client"], fresh["headers"]["admin"]
    body = {"project_id": fresh["project"], "requirement": "Build one more small API with tests."}
    old_done = client.post(f"{API}/tasks", json=body, headers=admin).json()["id"]
    old_running = client.post(f"{API}/tasks", json=body, headers=admin).json()["id"]
    new_done = client.post(f"{API}/tasks", json=body, headers=admin).json()["id"]
    long_ago = datetime.utcnow() - timedelta(days=90)
    with client.factory() as db:
        for tid, status, when in (
            (old_done, "COMPLETED", long_ago),
            (old_running, "TESTING", long_ago),
            (new_done, "COMPLETED", datetime.utcnow()),
        ):
            t = db.get(Task, uuid.UUID(tid))
            t.status, t.created_at = status, when
        db.add(
            ApprovalRequest(
                task_id=uuid.UUID(old_done),
                kind="plan",
                status="approved",
                resume_status="PLANNING",
            )
        )
        db.commit()
    for tid in (old_done, old_running, new_done):
        (_task_dir(tid) / "iter_1").mkdir(parents=True)
        (_task_dir(tid) / "iter_1" / "f.py").write_text("x = 1\n")

    url = f"{API}/orgs/{fresh['org_a']}/retention/run"
    assert client.post(url, headers=admin).json() == {
        "purged_tasks": 0
    }  # no retention set: keep all
    _patch(fresh, retention_days=30)
    assert client.post(url, headers=admin).json() == {"purged_tasks": 1}
    assert client.get(f"{API}/tasks/{old_done}", headers=admin).status_code == 404
    assert (
        client.get(f"{API}/tasks/{old_running}", headers=admin).status_code == 200
    )  # still running
    assert client.get(f"{API}/tasks/{new_done}", headers=admin).status_code == 200  # recent
    assert not _task_dir(old_done).exists() and _task_dir(old_running).exists()
    entry = audit(fresh, action="org.retention_run")[0]
    assert entry["detail"]["purged_tasks"] == 1  # the audit trail of the purge itself is kept


def test_export_is_complete_and_free_of_secrets(fresh):  # noqa: F811
    client, admin = fresh["client"], fresh["headers"]["admin"]
    r = client.get(f"{API}/orgs/{fresh['org_a']}/export", headers=admin)
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"organization.json", "members.json", "projects.json", "tasks.json"} <= names
    members = json.loads(z.read("members.json"))
    assert {m["email"] for m in members} >= {"admin_a@example.com", "viewer_a@example.com"}
    assert [t["id"] for t in json.loads(z.read("tasks.json"))] == [fresh["task"]]
    blob = b"".join(z.read(n) for n in names).decode()
    for forbidden in (
        "password_hash",
        "$2b$",
        "refresh_token",
        "access_token",
        "admin_b@example.com",
    ):
        assert forbidden not in blob


def test_delete_data_needs_the_slug_keeps_the_org_and_removes_files(fresh):  # noqa: F811
    client, admin = fresh["client"], fresh["headers"]["admin"]
    (_task_dir(fresh["task"]) / "iter_1").mkdir(parents=True)
    (_task_dir(fresh["task"]) / "iter_1" / "f.py").write_text("x = 1\n")
    url = f"{API}/orgs/{fresh['org_a']}"
    slug = client.get(url, headers=admin).json()["slug"]
    assert (
        client.request("DELETE", f"{url}/data", json={"confirm": "nope"}, headers=admin).status_code
        == 422
    )
    assert (
        client.get(f"{API}/tasks/{fresh['task']}", headers=admin).status_code == 200
    )  # nothing happened
    r = client.request("DELETE", f"{url}/data", json={"confirm": slug}, headers=admin)
    assert r.json() == {"deleted_tasks": 1}
    assert client.get(f"{API}/tasks", headers=admin).json() == []
    assert client.get(f"{API}/projects", headers=admin).json() == []
    assert not _task_dir(fresh["task"]).exists()
    assert client.get(url, headers=admin).status_code == 200  # the org and its members remain
    assert len(client.get(f"{url}/members", headers=admin).json()) == 4
    assert audit(fresh, action="org.delete_data")  # and so does the audit trail


def test_removing_a_missing_workspace_is_a_no_op(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "ws"))
    retention_service._remove_workspace(uuid.uuid4())  # nothing there: must not raise
