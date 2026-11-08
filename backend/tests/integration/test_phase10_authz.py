"""Phase 10 authorization: the endpoint x role matrix, cross-organization isolation, role changes.

The matrix is checked for COMPLETENESS against `app.routes`: a route that is added without a matrix
entry fails `test_every_route_is_in_the_matrix`, so a new endpoint cannot silently ship unprotected.
"""

import uuid

import bcrypt
import pytest
from starlette.routing import WebSocketRoute

from app.config import settings
from app.main import app
from app.services.org_service import ROLE_RANK
from app.utils import security
from tests.conftest import build_client, register_and_login

API = "/api/v1"
_REAL_GENSALT = bcrypt.gensalt  # captured before any test patches it

# (method, route template) -> minimum role. "public": no auth. "user": any signed-in user, no org.
MATRIX: dict[tuple[str, str], str] = {
    ("GET", "/health"): "public",
    ("GET", "/health/ready"): "public",
    ("GET", "/metrics"): "public",  # 404 unless METRICS_ENABLED; bearer token when configured
    ("GET", "/docs"): "public",
    ("HEAD", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("HEAD", "/docs/oauth2-redirect"): "public",
    ("GET", "/openapi.json"): "public",
    ("HEAD", "/openapi.json"): "public",
    ("GET", "/redoc"): "public",
    ("HEAD", "/redoc"): "public",
    ("GET", f"{API}/auth/config"): "public",
    ("POST", f"{API}/auth/login"): "public",
    ("POST", f"{API}/auth/logout"): "public",
    ("POST", f"{API}/auth/refresh"): "public",
    ("POST", f"{API}/auth/register"): "public",
    ("GET", f"{API}/auth/sso/login"): "public",
    ("GET", f"{API}/auth/sso/callback"): "public",
    ("POST", f"{API}/auth/logout-all"): "user",
    ("GET", f"{API}/auth/me"): "user",
    ("GET", f"{API}/orgs"): "user",
    ("POST", f"{API}/orgs"): "user",
    # --- organization administration (organization in the PATH: non-members get 404) ---
    ("GET", f"{API}/orgs/{{org_id}}"): "viewer",
    ("GET", f"{API}/orgs/{{org_id}}/usage"): "viewer",
    ("GET", f"{API}/orgs/{{org_id}}/members"): "viewer",
    ("PATCH", f"{API}/orgs/{{org_id}}"): "admin",
    # --- Phase 11: integrations and delivery ---
    ("PUT", f"{API}/orgs/{{org_id}}/integrations/github"): "admin",
    ("GET", f"{API}/orgs/{{org_id}}/tokens"): "admin",
    ("POST", f"{API}/orgs/{{org_id}}/tokens"): "admin",
    ("DELETE", f"{API}/orgs/{{org_id}}/tokens/{{token_id}}"): "admin",
    ("GET", f"{API}/orgs/{{org_id}}/webhooks"): "admin",
    ("POST", f"{API}/orgs/{{org_id}}/webhooks"): "admin",
    ("DELETE", f"{API}/orgs/{{org_id}}/webhooks/{{webhook_id}}"): "admin",
    ("POST", f"{API}/orgs/{{org_id}}/webhooks/{{webhook_id}}/test"): "admin",
    ("GET", f"{API}/orgs/{{org_id}}/webhooks/{{webhook_id}}/deliveries"): "admin",
    ("GET", f"{API}/tasks/{{task_id}}/publish"): "viewer",
    ("POST", f"{API}/tasks/{{task_id}}/publish"): "developer",
    ("POST", f"{API}/publish/{{publish_id}}/approve"): "approver",
    ("POST", f"{API}/publish/{{publish_id}}/reject"): "approver",
    ("GET", f"{API}/orgs/{{org_id}}/audit"): "admin",
    ("GET", f"{API}/orgs/{{org_id}}/export"): "admin",
    ("POST", f"{API}/orgs/{{org_id}}/members"): "admin",
    ("PATCH", f"{API}/orgs/{{org_id}}/members/{{user_id}}"): "admin",
    ("DELETE", f"{API}/orgs/{{org_id}}/members/{{user_id}}"): "admin",
    ("POST", f"{API}/orgs/{{org_id}}/retention/run"): "admin",
    ("DELETE", f"{API}/orgs/{{org_id}}/data"): "admin",
    # --- work (organization from X-Org-Id: non-members get 403) ---
    ("GET", f"{API}/agents"): "viewer",
    ("GET", f"{API}/agents/{{name}}/status"): "viewer",
    ("GET", f"{API}/analytics/agents"): "viewer",
    ("GET", f"{API}/analytics/overview"): "viewer",
    ("GET", f"{API}/analytics/tasks/{{task_id}}"): "viewer",
    ("GET", f"{API}/analytics/iterations/{{iteration_id}}"): "viewer",
    ("GET", f"{API}/projects"): "viewer",
    ("GET", f"{API}/projects/{{project_id}}"): "viewer",
    ("POST", f"{API}/projects"): "developer",
    ("PUT", f"{API}/projects/{{project_id}}"): "developer",
    ("DELETE", f"{API}/projects/{{project_id}}"): "developer",
    ("GET", f"{API}/tasks"): "viewer",
    ("POST", f"{API}/tasks"): "developer",
    ("GET", f"{API}/tasks/{{task_id}}"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/agent-runs"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/approvals"): "viewer",
    ("POST", f"{API}/tasks/{{task_id}}/approvals/{{approval_id}}/approve"): "approver",
    ("POST", f"{API}/tasks/{{task_id}}/approvals/{{approval_id}}/reject"): "approver",
    ("POST", f"{API}/tasks/{{task_id}}/cancel"): "developer",
    ("GET", f"{API}/tasks/{{task_id}}/download"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/events"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/files"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/files/{{file_path:path}}"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/iterations"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/iterations/{{number}}/logs"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/iterations/{{number}}/test-results"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/plan"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/report"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/report.md"): "viewer",
    ("GET", f"{API}/tasks/{{task_id}}/requirements"): "viewer",
    ("POST", f"{API}/tasks/{{task_id}}/resume"): "developer",
    ("POST", f"{API}/tasks/{{task_id}}/retry"): "developer",
    ("POST", f"{API}/tasks/{{task_id}}/source"): "developer",
    ("POST", f"{API}/tasks/{{task_id}}/start"): "developer",
    ("POST", f"{API}/tasks/{{task_id}}/status"): "developer",
    ("GET", f"{API}/iterations/{{iteration_id}}"): "viewer",
    ("GET", f"{API}/iterations/{{iteration_id}}/diff"): "viewer",
    ("GET", f"{API}/iterations/{{iteration_id}}/files/{{file_path:path}}"): "viewer",
    ("GET", f"{API}/iterations/{{iteration_id}}/logs"): "viewer",
}
PATH_ORG = "/orgs/{org_id}"  # routes whose organization is in the path


def _walk(routes, prefix: str = ""):
    """Every HTTP route, however the framework nests it.

    Older FastAPI flattens included routers into `app.routes`; newer versions keep each include as a
    lazy `_IncludedRouter` that holds `original_router` and an include prefix. Both are handled, so the
    completeness check keeps working across framework upgrades.
    """
    for route in routes:
        if isinstance(route, WebSocketRoute):
            continue
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk(inner.routes, prefix + route.include_context.prefix)
            continue
        for method in getattr(route, "methods", None) or ():
            yield (method, prefix + route.path)


def _app_routes() -> set[tuple[str, str]]:
    return set(_walk(app.routes))


def test_every_route_is_in_the_matrix():
    routes = _app_routes()
    assert routes - set(MATRIX) == set(), "route(s) without an authorization matrix entry"
    assert set(MATRIX) - routes == set(), "matrix entries for routes that no longer exist"


# ---- the world -------------------------------------------------------------------------------


def _fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Password hashing at the minimum cost: these tests create dozens of users."""
    monkeypatch.setattr(security.bcrypt, "gensalt", lambda: _REAL_GENSALT(rounds=4))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Shared by the read-only matrix tests (one set of users for the whole module)."""
    mp = pytest.MonkeyPatch()
    _fast_bcrypt(mp)
    mp.setattr(settings, "workspace_root", str(tmp_path_factory.mktemp("ws")))
    mp.setattr(settings, "documentation_agent_enabled", False)
    client, engine = build_client(tmp_path_factory.mktemp("authz") / "t.db")
    yield _build_world(client)
    app.dependency_overrides.clear()
    engine.dispose()
    mp.undo()


@pytest.fixture
def fresh(client, monkeypatch):
    """A new world per test, for tests that change data or roles."""
    _fast_bcrypt(monkeypatch)
    return _build_world(client)


def _build_world(client):
    users = {}
    for name in ("admin_a", "approver_a", "developer_a", "viewer_a", "admin_b", "stranger"):
        users[name] = register_and_login(client, f"{name}@example.com")

    def org_id(headers):
        return client.get(f"{API}/orgs", headers=headers).json()[0]["id"]

    org_a, org_b = org_id(users["admin_a"]), org_id(users["admin_b"])
    for who, role in (
        ("approver_a", "approver"),
        ("developer_a", "developer"),
        ("viewer_a", "viewer"),
    ):
        r = client.post(
            f"{API}/orgs/{org_a}/members",
            json={"email": f"{who}@example.com", "role": role},
            headers=users["admin_a"],
        )
        assert r.status_code == 201, r.text
    headers = {
        "admin": {**users["admin_a"], "X-Org-Id": org_a},
        "approver": {**users["approver_a"], "X-Org-Id": org_a},
        "developer": {**users["developer_a"], "X-Org-Id": org_a},
        "viewer": {**users["viewer_a"], "X-Org-Id": org_a},
    }
    project = client.post(f"{API}/projects", json={"name": "p"}, headers=headers["admin"]).json()
    task = client.post(
        f"{API}/tasks",
        json={"project_id": project["id"], "requirement": "Build a small API with tests please."},
        headers=headers["admin"],
    ).json()
    return {
        "client": client,
        "users": users,
        "org_a": org_a,
        "org_b": org_b,
        "headers": headers,
        "project": project["id"],
        "task": task["id"],
    }


def _url(world, template: str) -> str:
    return template.replace(":path", "").format(
        org_id=world["org_a"],
        user_id=uuid.uuid4(),
        task_id=world["task"],
        project_id=world["project"],
        approval_id=uuid.uuid4(),
        token_id=uuid.uuid4(),
        webhook_id=uuid.uuid4(),
        publish_id=uuid.uuid4(),
        iteration_id=uuid.uuid4(),
        number=1,
        file_path="app/x.py",
        name="Planner",
    )


def _call(client, method, url, headers):
    return client.request(method, url, headers=headers, json={} if method != "GET" else None)


ORG_ROUTES = sorted((k, v) for k, v in MATRIX.items() if v in ROLE_RANK)
ROLES = sorted(ROLE_RANK, key=ROLE_RANK.get)


@pytest.mark.parametrize(("route", "minimum"), ORG_ROUTES, ids=lambda x: str(x))
def test_each_role_is_allowed_or_denied_exactly_as_the_matrix_says(world, route, minimum):
    method, template = route
    client = world["client"]
    url = _url(world, template)
    for role in ROLES:
        status = _call(client, method, url, world["headers"][role]).status_code
        if ROLE_RANK[role] >= ROLE_RANK[minimum]:
            assert status not in (401, 403), f"{role} should reach {method} {template}: {status}"
        else:
            assert status == 403, f"{role} must be refused {method} {template}: {status}"


@pytest.mark.parametrize(("route", "minimum"), ORG_ROUTES, ids=lambda x: str(x))
def test_a_non_member_and_anonymous_callers_are_refused(world, route, minimum):
    method, template = route
    client = world["client"]
    url = _url(world, template)
    outsider = {**world["users"]["stranger"], "X-Org-Id": world["org_a"]}
    status = _call(client, method, url, outsider).status_code
    assert status == (404 if template.split(API)[-1].startswith("/orgs/{org_id}") else 403)
    assert _call(client, method, url, {}).status_code == 401


def test_user_level_and_public_routes(world):
    client = world["client"]
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/orgs").status_code == 401
    assert client.get(f"{API}/auth/me", headers=world["users"]["stranger"]).status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get(f"{API}/auth/config").json() == {"sso_enabled": False}


# ---- isolation between organizations ---------------------------------------------------------


def test_organization_b_cannot_see_or_touch_organization_a(fresh):
    client, hb = fresh["client"], {**fresh["users"]["admin_b"], "X-Org-Id": fresh["org_b"]}
    task, project = fresh["task"], fresh["project"]
    for path in (
        f"/tasks/{task}",
        f"/tasks/{task}/report",
        f"/tasks/{task}/events",
        f"/tasks/{task}/files",
        f"/tasks/{task}/download",
        f"/analytics/tasks/{task}",
        f"/projects/{project}",
    ):
        assert client.get(f"{API}{path}", headers=hb).status_code == 404, path
    assert client.post(f"{API}/tasks/{task}/start", headers=hb).status_code == 404
    assert client.post(f"{API}/tasks/{task}/cancel", headers=hb).status_code == 404
    assert client.delete(f"{API}/projects/{project}", headers=hb).status_code == 404
    assert client.get(f"{API}/tasks", headers=hb).json() == []
    assert client.get(f"{API}/projects", headers=hb).json() == []
    assert client.get(f"{API}/analytics/overview", headers=hb).json()["tasks_total"] == 0
    # B cannot create a task inside A's project either
    r = client.post(
        f"{API}/tasks", json={"project_id": project, "requirement": "x" * 30}, headers=hb
    )
    assert r.status_code == 404


def test_one_user_in_two_orgs_sees_only_the_active_one(fresh):
    client, admin = fresh["client"], fresh["users"]["admin_a"]
    other = client.post(f"{API}/orgs", json={"name": "Second"}, headers=admin).json()["id"]
    assert client.get(f"{API}/tasks", headers={**admin, "X-Org-Id": fresh["org_a"]}).json() != []
    assert client.get(f"{API}/tasks", headers={**admin, "X-Org-Id": other}).json() == []
    assert (
        client.get(f"{API}/tasks/{fresh['task']}", headers={**admin, "X-Org-Id": other}).status_code
        == 404
    )
    assert (
        client.get(f"{API}/tasks", headers={**admin, "X-Org-Id": "not-a-uuid"}).status_code == 403
    )


def test_websocket_requires_membership_of_the_task_org(fresh):
    from starlette.websockets import WebSocketDisconnect

    from app.database.models import Task

    client = fresh["client"]
    with client.factory() as db:  # a finished task, so a permitted stream ends by itself
        db.get(Task, uuid.UUID(fresh["task"])).status = "CANCELLED"
        db.commit()
    token_b = fresh["users"]["admin_b"]["Authorization"].split()[1]
    token_a = fresh["users"]["admin_a"]["Authorization"].split()[1]
    path = f"/ws/tasks/{fresh['task']}"

    def connect(url):
        with client.websocket_connect(url) as ws:
            try:
                while True:
                    ws.receive_json()
            except WebSocketDisconnect:
                return

    for denied in (
        f"{path}?token={token_b}",  # B's own org has no such task
        f"{path}?token={token_b}&org={fresh['org_a']}",  # B is not a member of A
        f"{path}?token=garbage",
    ):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(denied) as ws:
                ws.receive_json()
    connect(f"{path}?token={token_a}&org={fresh['org_a']}")  # a member: stream, then close


# ---- roles change immediately -----------------------------------------------------------------


def test_role_changes_and_removal_apply_to_the_next_request(fresh):
    client, admin = fresh["client"], fresh["headers"]["admin"]
    dev = fresh["headers"]["developer"]
    members = client.get(f"{API}/orgs/{fresh['org_a']}/members", headers=admin).json()
    dev_id = next(m["user_id"] for m in members if m["email"] == "developer_a@example.com")
    assert client.post(f"{API}/projects", json={"name": "ok"}, headers=dev).status_code == 201
    r = client.patch(
        f"{API}/orgs/{fresh['org_a']}/members/{dev_id}", json={"role": "viewer"}, headers=admin
    )
    assert r.status_code == 200
    assert client.post(f"{API}/projects", json={"name": "no"}, headers=dev).status_code == 403
    assert (
        client.delete(f"{API}/orgs/{fresh['org_a']}/members/{dev_id}", headers=admin).status_code
        == 204
    )
    assert client.get(f"{API}/projects", headers=dev).status_code == 403  # no longer a member


def test_the_last_admin_cannot_be_demoted_or_removed(fresh):
    client, admin = fresh["client"], fresh["headers"]["admin"]
    me = client.get(f"{API}/auth/me", headers=admin).json()["id"]
    url = f"{API}/orgs/{fresh['org_a']}/members/{me}"
    assert client.patch(url, json={"role": "viewer"}, headers=admin).status_code == 409
    assert client.delete(url, headers=admin).status_code == 409


def test_adding_members_needs_a_registered_user_and_rejects_duplicates(fresh):
    client, admin = fresh["client"], fresh["headers"]["admin"]
    url = f"{API}/orgs/{fresh['org_a']}/members"
    assert client.post(url, json={"email": "nobody@example.com"}, headers=admin).status_code == 404
    dup = client.post(url, json={"email": "viewer_a@example.com"}, headers=admin)
    assert dup.status_code == 409


def test_approval_decisions_record_who_decided(fresh):
    from app.database.models import ApprovalRequest, Task

    client = fresh["client"]
    with client.factory() as db:
        task = db.get(Task, uuid.UUID(fresh["task"]))
        task.status = "AWAITING_APPROVAL"
        req = ApprovalRequest(
            task_id=task.id, kind="plan", status="pending", resume_status="PLANNING", summary="s"
        )
        db.add(req)
        db.commit()
        req_id = req.id
    url = f"{API}/tasks/{fresh['task']}/approvals/{req_id}/reject"
    assert client.post(url, headers=fresh["headers"]["developer"]).status_code == 403
    assert client.post(url, headers=fresh["headers"]["approver"]).status_code == 200
    with client.factory() as db:
        decided = db.get(ApprovalRequest, req_id)
        approver_id = client.get(f"{API}/auth/me", headers=fresh["users"]["approver_a"]).json()[
            "id"
        ]
        assert str(decided.decided_by) == approver_id
