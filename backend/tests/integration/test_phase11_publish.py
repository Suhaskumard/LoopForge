"""Phase 11 gate: pull-request delivery against a mock Git server; no push without approval."""

import json
import uuid
from pathlib import Path

import httpx
import pytest

from app.database.models import AuditLog, Iteration, PublishRequest, Task
from app.services import github_service, publish_service, workspace
from app.services.publish_service import PublishError
from tests.conftest import register_and_login

API = "/api/v1"
FILES = {"app/main.py": "print('hi')\n", "tests/test_main.py": "def test_x():\n    assert True\n"}


class MockGitHub:
    """Records every request; answers like the parts of the GitHub REST API we use."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_on: str | None = None
        self.check_runs: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.calls.append((request.method, path, body))
        assert request.headers["Authorization"] == "Bearer ghp_" + "a" * 36
        if self.fail_on and self.fail_on in path:
            return httpx.Response(422, json={"message": "nope"})
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base"}})
        if path.endswith("/git/commits/base"):
            return httpx.Response(200, json={"tree": {"sha": "t0"}})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "t1"})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "c1"})
        if path.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if path.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7"})
        if path.endswith("/check-runs"):
            return httpx.Response(200, json={"check_runs": self.check_runs})
        return httpx.Response(404, json={})

    @property
    def writes(self) -> list[tuple[str, str, dict]]:
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def gh(monkeypatch):
    mock = MockGitHub()
    monkeypatch.setattr(
        github_service, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(mock))
    )
    return mock


def _world(client, with_token=True):
    admin = register_and_login(client, "admin@example.com")
    org = client.get(f"{API}/orgs", headers=admin).json()[0]["id"]
    for who, role in (("approver", "approver"), ("viewer", "viewer")):
        register_and_login(client, f"{who}@example.com")
        r = client.post(
            f"{API}/orgs/{org}/members",
            json={"email": f"{who}@example.com", "role": role},
            headers=admin,
        )
        assert r.status_code == 201, r.text
    h = {
        "admin": {**admin, "X-Org-Id": org},
        "approver": {**register_and_login(client, "approver@example.com"), "X-Org-Id": org},
        "viewer": {**register_and_login(client, "viewer@example.com"), "X-Org-Id": org},
    }
    if with_token:
        r = client.put(
            f"{API}/orgs/{org}/integrations/github",
            json={"token": "ghp_" + "a" * 36},
            headers=admin,
        )
        assert r.status_code == 200, r.text
    return org, h


def _completed_task(client, h, files=FILES, status="COMPLETED") -> str:
    project = client.post(f"{API}/projects", json={"name": "p"}, headers=h["admin"]).json()
    task = client.post(
        f"{API}/tasks",
        json={"project_id": project["id"], "requirement": "Build a small API with tests."},
        headers=h["admin"],
    ).json()
    with client.factory() as db:
        db.add(Iteration(task_id=uuid.UUID(task["id"]), iteration_number=1, status="passed"))
        t = db.get(Task, uuid.UUID(task["id"]))
        t.status = status
        db.commit()
    base = workspace.iteration_dir(uuid.UUID(task["id"]), 1)
    for rel, text in files.items():
        p = Path(base) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return task["id"]


def _request(client, h, task_id, who="admin"):
    return client.post(f"{API}/tasks/{task_id}/publish", json={"repo": "o/r"}, headers=h[who])


def _actions(client, org, h):
    return [e["action"] for e in client.get(f"{API}/orgs/{org}/audit", headers=h["admin"]).json()]


def test_nothing_is_pushed_before_approval(client, gh):
    org, h = _world(client)
    task = _completed_task(client, h)
    r = _request(client, h, task)
    assert r.status_code == 201 and r.json()["status"] == "requested"
    assert gh.calls == []  # not even a read
    assert "publish.requested" in _actions(client, org, h)


def test_approval_opens_the_pull_request(client, gh):
    org, h = _world(client)
    task = _completed_task(client, h)
    pid = _request(client, h, task).json()["id"]
    r = client.post(f"{API}/publish/{pid}/approve", headers=h["approver"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "pushed" and out["pr_url"] == "https://github.com/o/r/pull/7"
    tree = next(b for m, p, b in gh.calls if p.endswith("/git/trees"))
    assert {e["path"] for e in tree["tree"]} == set(FILES)
    pr = next(b for m, p, b in gh.calls if p.endswith("/pulls"))
    assert pr["head"].startswith("loopforge/task-") and "LoopForge engineering report" in pr["body"]
    actions = _actions(client, org, h)
    assert {"publish.requested", "publish.approved", "publish.pushed"} <= set(actions)
    # approving again never pushes twice
    n = len(gh.writes)
    assert client.post(f"{API}/publish/{pid}/approve", headers=h["approver"]).status_code == 409
    assert len(gh.writes) == n


def test_requester_cannot_approve_own_request(client, gh):
    _, h = _world(client)
    task = _completed_task(client, h)
    pid = _request(client, h, task).json()["id"]
    r = client.post(f"{API}/publish/{pid}/approve", headers=h["admin"])
    assert r.status_code == 403 and gh.calls == []


def test_rejected_request_never_pushes(client, gh):
    _, h = _world(client)
    task = _completed_task(client, h)
    pid = _request(client, h, task).json()["id"]
    assert client.post(f"{API}/publish/{pid}/reject", headers=h["approver"]).status_code == 200
    assert client.post(f"{API}/publish/{pid}/approve", headers=h["approver"]).status_code == 409
    assert gh.calls == []


def test_push_function_refuses_without_recorded_approval(client, gh):
    org, h = _world(client)
    task = _completed_task(client, h)
    pid = uuid.UUID(_request(client, h, task).json()["id"])
    with client.factory() as db:
        with pytest.raises(PublishError):
            publish_service.push(db, org_id=uuid.UUID(org), publish_id=pid, request=None)
        row = db.get(PublishRequest, pid)
        row.status = "approved"  # approved status but no decision recorded (decided_by is None)
        db.commit()
        with pytest.raises(PublishError):
            publish_service.push(db, org_id=uuid.UUID(org), publish_id=pid, request=None)
    assert gh.calls == []


def test_only_completed_tasks_and_roles(client, gh):
    _, h = _world(client)
    running = _completed_task(client, h, status="TESTING")
    assert _request(client, h, running).status_code == 409
    done = _completed_task(client, h)
    assert _request(client, h, done, who="viewer").status_code == 403
    pid = _request(client, h, done).json()["id"]
    assert _request(client, h, done).status_code == 409  # one open request at a time
    assert client.post(f"{API}/publish/{pid}/approve", headers=h["viewer"]).status_code == 403
    assert gh.calls == []


def test_secrets_in_the_change_set_block_publishing(client, gh):
    _, h = _world(client)
    task = _completed_task(client, h, files={"app/cfg.py": 'API_KEY = "sk-' + "a" * 30 + '"\n'})
    r = _request(client, h, task)
    assert r.status_code == 422 and "secrets" in r.json()["error"]["message"]
    assert gh.calls == []


def test_requires_configured_token(client, gh):
    _, h = _world(client, with_token=False)
    task = _completed_task(client, h)
    assert _request(client, h, task).status_code == 422


def test_provider_error_is_recorded_not_raised(client, gh):
    org, h = _world(client)
    task = _completed_task(client, h)
    pid = _request(client, h, task).json()["id"]
    gh.fail_on = "/git/refs"
    out = client.post(f"{API}/publish/{pid}/approve", headers=h["approver"]).json()
    assert out["status"] == "failed" and "HTTP 422" in out["error"]
    assert "ghp_" not in json.dumps(out)
    assert "publish.failed" in _actions(client, org, h)


def test_cross_org_isolation(client, gh):
    _, h = _world(client)
    task = _completed_task(client, h)
    pid = _request(client, h, task).json()["id"]
    other = register_and_login(client, "other@example.com")
    assert client.post(f"{API}/publish/{pid}/approve", headers=other).status_code == 404
    assert client.get(f"{API}/tasks/{task}/publish", headers=other).status_code == 404
    assert gh.calls == []


def test_ci_state_is_informational(client, gh):
    _, h = _world(client)
    task = _completed_task(client, h)
    pid = _request(client, h, task).json()["id"]
    client.post(f"{API}/publish/{pid}/approve", headers=h["approver"])
    assert (
        client.get(f"{API}/tasks/{task}/publish", headers=h["viewer"]).json()[0]["ci_state"]
        == "none"
    )
    gh.check_runs = [{"status": "in_progress"}]
    with client.factory() as db:
        db.get(PublishRequest, uuid.UUID(pid)).ci_state = None
        db.commit()
    assert (
        client.get(f"{API}/tasks/{task}/publish", headers=h["viewer"]).json()[0]["ci_state"]
        == "pending"
    )
    gh.check_runs = [{"status": "completed", "conclusion": "failure"}]
    assert (
        client.get(f"{API}/tasks/{task}/publish", headers=h["viewer"]).json()[0]["ci_state"]
        == "failure"
    )
    assert client.get(f"{API}/tasks/{task}", headers=h["viewer"]).json()["status"] == "COMPLETED"


def test_github_token_is_stored_encrypted(client, gh):
    org, _ = _world(client)
    from app.database.models import OrgIntegration

    with client.factory() as db:
        row = db.query(OrgIntegration).one()
        assert "ghp_" not in row.token_enc
        assert publish_service.has_token(db, uuid.UUID(org))
    assert AuditLog  # audit model imported for the matrix of actions above
