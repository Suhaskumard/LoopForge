# ruff: noqa: E501
"""Phase 18: one pagination contract on every collection endpoint that can grow."""

from app.main import app
from tests.conftest import register_and_login

API = "/api/v1"

# Collections that are bounded by design, with the reason. Everything else that returns an array
# must accept `limit` (and `offset`); a new unbounded list route fails this test until one or the
# other is done on purpose.
BOUNDED = {
    "/api/v1/agents": "fixed catalogue of the six agents",
    "/api/v1/analytics/agents": "one row per agent name",
    "/api/v1/auth/sessions": "a user's own refresh-token families",
    "/api/v1/orgs": "the organizations one user belongs to",
    "/api/v1/templates": "built-in task templates",
    "/api/v1/tasks/{task_id}/files": "bounded by the workspace size policy",
    "/api/v1/tasks/{task_id}/iterations": "bounded by max_iterations (<= 10)",
    "/api/v1/iterations/{iteration_id}/logs": "one iteration's execution logs",
    "/api/v1/tasks/{task_id}/iterations/{number}/logs": "one iteration's execution logs",
    "/api/v1/tasks/{task_id}/iterations/{number}/test-results": "one iteration's results",
    "/api/v1/tasks/{task_id}/approvals/{approval_id}/comments": "comments on one approval",
    "/api/v1/tasks/{task_id}/comments": "line notes on one task (people write them by hand)",
}


def _array_get_routes() -> dict[str, list[str]]:
    out = {}
    for path, item in app.openapi()["paths"].items():
        get = item.get("get")
        if not get:
            continue
        schema = get["responses"].get("200", {}).get("content", {}).get("application/json", {})
        if schema.get("schema", {}).get("type") == "array":
            out[path] = [p["name"] for p in get.get("parameters", [])]
    return out


def test_every_unbounded_list_route_paginates_and_every_exception_is_justified():
    routes = _array_get_routes()
    missing = sorted(p for p, names in routes.items() if "limit" not in names and p not in BOUNDED)
    assert missing == [], f"list routes without limit/offset and not declared bounded: {missing}"
    stale = sorted(p for p in BOUNDED if p not in routes)
    assert stale == [], f"BOUNDED names routes that no longer exist: {stale}"
    for path, names in routes.items():
        if "limit" in names:
            assert "offset" in names, path
    assert len(routes) - len(BOUNDED) >= 14  # the paginated set is substantial, not a stub


def _setup(client):
    h = register_and_login(client, "owner@x.com")
    oid = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return oid, {**h, "X-Org-Id": oid}


def test_members_page_with_total_count_and_next_link(client):
    oid, h = _setup(client)
    for i in range(5):
        register_and_login(client, f"m{i}@x.com")
        client.post(f"{API}/orgs/{oid}/members", json={"email": f"m{i}@x.com"}, headers=h)
    full = client.get(f"{API}/orgs/{oid}/members", headers=h)
    assert (
        len(full.json()) == 6
        and full.headers["x-total-count"] == "6"
        and "link" not in full.headers
    )
    first = client.get(f"{API}/orgs/{oid}/members?limit=4", headers=h)
    assert len(first.json()) == 4 and first.headers["x-total-count"] == "6"
    assert first.headers["link"] == f'</api/v1/orgs/{oid}/members?limit=4&offset=4>; rel="next"'
    last = client.get(f"{API}/orgs/{oid}/members?limit=4&offset=4", headers=h)
    assert len(last.json()) == 2 and "link" not in last.headers
    ids = [m["user_id"] for m in first.json() + last.json()]
    assert len(set(ids)) == 6  # stable order: no duplicates or gaps across pages
    assert client.get(f"{API}/orgs/{oid}/members?offset=99", headers=h).json() == []


def test_limits_are_validated_and_capped(client):
    oid, h = _setup(client)
    for bad in ("limit=0", "limit=501", "limit=-1", "offset=-1"):
        assert client.get(f"{API}/orgs/{oid}/members?{bad}", headers=h).status_code == 422, bad
    assert client.get(f"{API}/orgs/{oid}/members?limit=500", headers=h).status_code == 200


def test_task_scoped_lists_page_too(client):
    oid, h = _setup(client)
    project = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    task = client.post(
        f"{API}/tasks",
        json={"project_id": project["id"], "requirement": "Build employees"},
        headers=h,
    ).json()
    for path in ("events", "requirements", "agent-runs", "approvals", "publish"):
        r = client.get(f"{API}/tasks/{task['id']}/{path}?limit=1", headers=h)
        assert r.status_code == 200 and "x-total-count" in r.headers, path
