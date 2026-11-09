# ruff: noqa: E501, E402
"""Phase 18: the Python SDK against the REAL LoopForge app (no mocks of the server).

The SDK's HTTP transport is pointed straight at the FastAPI app, so every call crosses the real
routing, auth, rate-limit, idempotency, pagination and error-envelope code.
"""

import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sdk" / "python"))

from loopforge_sdk import (  # noqa: E402
    OPERATIONS,
    APIError,
    Conflict,
    LoopForge,
    NotFound,
    RateLimited,
    TransportError,
    Unauthorized,
    ValidationError,
)

from app.config import settings  # noqa: E402
from app.database.models import Project  # noqa: E402
from app.main import app  # noqa: E402


class AppTransport(httpx.BaseTransport):
    """Run requests through the ASGI app synchronously (what a network hop would carry)."""

    def __init__(self, test_client) -> None:
        self.c = test_client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        resp = self.c.request(
            request.method,
            str(request.url.path) + (f"?{request.url.query.decode()}" if request.url.query else ""),
            content=request.content,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content)


@pytest.fixture
def lf(client):
    sdk = LoopForge("http://testserver", transport=AppTransport(client), sleep=lambda s: None)
    sdk.register("sdk@x.com", "password123")
    sdk.login("sdk@x.com", "password123")
    sdk.org_id = sdk.orgs()[0]["id"]
    return sdk


# ---- contract: every operation the SDK names exists in the committed OpenAPI, and vice versa ----

# Operations deliberately without a named SDK method (reach them with lf.request()).
UNNAMED = {
    "agents", "analytics", "auth/mfa", "auth/sessions", "auth/sso", "auth/password-reset",
    "auth/verify-email", "auth/resend-verification", "auth/logout", "invites", "iterations",
    "me/onboarding", "notifications", "scim", "templates", "tasks/{task_id}/approvals",
    "tasks/{task_id}/source", "tasks/{task_id}/status", "tasks/{task_id}/resume",
    "tasks/{task_id}/plan", "tasks/{task_id}/requirements", "tasks/{task_id}/agent-runs",
    "tasks/{task_id}/download", "tasks/{task_id}/iterations", "tasks/{task_id}/files/",
    "publish/{publish_id}", "orgs/{org_id}/audit", "orgs/{org_id}/data", "orgs/{org_id}/export",
    "orgs/{org_id}/integrations", "orgs/{org_id}/invites", "orgs/{org_id}/members/{user_id}",
    "orgs/{org_id}/my-usage", "orgs/{org_id}/retention", "orgs/{org_id}/scim-tokens",
    "orgs/{org_id}/webhooks/{webhook_id}/test", "orgs/{org_id}/webhooks/{webhook_id}/deliveries",
    "health/ready", "auth/config", "auth/logout-all", "projects/{project_id}",
    # Round 8/9: dashboard-facing views and loop intelligence (no SDK wrappers yet)
    "graph", "repairs", "forecast", "experiments/{experiment}", "tasks/{task_id}/comments",
    "tasks/{task_id}/watch", "tasks/{task_id}/rerun", "tasks/{task_id}/experiments",
    # Round 12
    "tasks/{task_id}/explanation", "pipelines", "orgs/{org_id}/routing",
}  # fmt: skip


# Unnamed operations matched on the whole path (a prefix match here would hide new routes).
EXACT_UNNAMED = {"orgs", "orgs/{org_id}", "orgs/{org_id}/members", "/health/ready", "health/ready"}


def test_every_named_operation_is_a_real_operation_with_the_right_method():
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    for name, (method, path) in OPERATIONS.items():
        assert path in spec["paths"], f"{name}: {path} is not in the API"
        assert method.lower() in spec["paths"][path], f"{name}: {method} {path} does not exist"
        assert callable(getattr(LoopForge, name)), name


def test_every_api_operation_is_named_in_the_sdk_or_listed_as_unnamed():
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    named = set(OPERATIONS.values())
    uncovered = []
    for path, item in spec["paths"].items():
        for method in item:
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if (method.upper(), path) in named:
                continue
            short = path.removeprefix("/api/v1/")
            exact = short in EXACT_UNNAMED or (method.upper(), short) in EXACT_UNNAMED
            if not exact and not any(short.startswith(u.rstrip("/")) for u in UNNAMED):
                uncovered.append(f"{method.upper()} {path}")
    assert uncovered == [], f"API operations neither in the SDK nor in UNNAMED: {uncovered}"


def test_sdk_version_matches_the_server_and_health_reports_it(lf):
    from app.version import __version__

    assert lf.health()["version"] == __version__
    assert __version__.replace("-", "") == "1.0.0rc1"
    from loopforge_sdk import __version__ as sdk_version

    assert sdk_version == __version__.replace("-", "")


# ---- behaviour ---------------------------------------------------------------------------------


def test_full_task_lifecycle_through_the_sdk(lf):
    project = lf.create_project("billing")
    task = lf.create_task(project["id"], "Add an invoice export endpoint with tests")
    assert task["status"] == "PENDING"
    assert lf.start_task(task["id"])["status"] in ("PLANNING", "BUILDING", "FAILED")
    assert lf.task(task["id"])["id"] == task["id"]
    assert [t["id"] for t in lf.tasks()] == [task["id"]]
    assert lf.project(project["id"])["name"] == "billing"
    assert isinstance(lf.task_files(task["id"]), list)
    assert lf.me()["email"] == "sdk@x.com" and lf.org()["id"] == lf.org_id
    with pytest.raises(Conflict):  # the fake LLM has nothing queued, so the run already failed
        lf.cancel_task(task["id"])
    pending = lf.create_task(project["id"], "Another task that we never start")
    assert lf.cancel_task(pending["id"])["status"] == "CANCELLED"


def test_paginated_iterators_cross_page_boundaries_without_gaps_or_repeats(lf):
    names = {f"p{i:02d}" for i in range(7)}
    for n in sorted(names):
        lf.create_project(n)
    got = [p["name"] for p in lf.paginate("/api/v1/projects", page_size=3)]
    assert sorted(got) == sorted(names) and len(got) == 7
    assert sorted(p["name"] for p in lf.projects()) == sorted(names)


def test_idempotent_creates_are_safe_to_retry(lf, client):
    key = uuid.uuid4().hex
    first = lf.create_project("once", idempotency_key=key)
    again = lf.create_project("once", idempotency_key=key)
    assert again["id"] == first["id"]
    with client.factory() as db:
        assert db.query(Project).filter_by(name="once").count() == 1
    with pytest.raises(ValidationError):  # same key, different body: a client bug
        lf.create_project("different", idempotency_key=key)


def test_errors_map_to_exception_types_with_status_code_and_request_id(lf):
    with pytest.raises(NotFound) as nf:
        lf.task(str(uuid.uuid4()))
    assert nf.value.status == 404 and nf.value.code == "not_found" and nf.value.request_id
    with pytest.raises(ValidationError):
        lf.create_project("")
    anon = LoopForge("http://testserver", transport=lf._http._transport, sleep=lambda s: None)
    with pytest.raises(Unauthorized):
        anon.me()
    with pytest.raises(APIError):
        lf.request("GET", "/api/v1/does-not-exist")


def test_rate_limit_is_retried_with_retry_after_then_surfaces(lf, monkeypatch):
    token = lf.create_token("ci", "developer")["token"]
    monkeypatch.setattr(settings, "api_token_rate_limit_per_minute", 2)
    waits: list[float] = []
    bot = LoopForge(
        "http://testserver", token=token, transport=lf._http._transport, max_retries=2,
        sleep=waits.append,
    )  # fmt: skip
    bot.projects().__next__ if False else list(bot.projects())
    list(bot.projects())
    with pytest.raises(RateLimited) as rl:  # third call in the window: retried twice, then raised
        list(bot.projects())
    assert len(waits) == 2 and all(w >= 1 for w in waits)  # honoured Retry-After, no hot loop
    assert rl.value.status == 429 and rl.value.retry_after and rl.value.retry_after >= 1


def test_a_post_without_an_idempotency_key_is_never_retried(lf, monkeypatch):
    calls = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(503, json={"error": {"code": "unavailable", "message": "down"}})

    bare = LoopForge("http://x", transport=httpx.MockTransport(flaky), sleep=lambda s: None)
    with pytest.raises(APIError):
        bare.request("POST", "/api/v1/anything", json={})
    assert calls == ["POST"]  # one attempt: a retry could double-create
    calls.clear()
    with pytest.raises(APIError):
        bare.request("POST", "/api/v1/anything", json={}, idempotency_key="k")
    assert len(calls) == 1 + bare.max_retries  # with a key, retrying is safe
    calls.clear()
    with pytest.raises(APIError):
        bare.request("GET", "/api/v1/anything")
    assert len(calls) == 1 + bare.max_retries


def test_transport_errors_are_retried_then_raised_as_transport_error():
    attempts = []

    def boom(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("refused")

    c = LoopForge(
        "http://x", transport=httpx.MockTransport(boom), sleep=lambda s: None, max_retries=2
    )
    with pytest.raises(TransportError):
        c.health()
    assert len(attempts) == 3


def test_usage_report_and_csv_and_token_and_webhook_helpers(lf, monkeypatch):
    monkeypatch.setattr(settings, "webhook_allow_private_hosts", True)
    assert lf.usage()["tasks_created"] == 0
    assert lf.usage_report(group_by="agent")["totals"]["tokens"] == 0
    assert lf.usage_report_csv().splitlines()[0].startswith("period_from,period_to,group_by")
    tok = lf.create_token("ci", "viewer")
    assert tok["token"].startswith("lfk_") and [t["name"] for t in lf.tokens()] == ["ci"]
    lf.revoke_token(tok["id"])
    hook = lf.create_webhook("https://hooks.test/in", ["task.completed"])
    assert hook["secret"].startswith("whsec_")
    rotated = lf.rotate_webhook_secret(hook["id"])
    assert rotated["secret"] != hook["secret"]
    assert [h["id"] for h in lf.webhooks()] == [hook["id"]]
    lf.delete_webhook(hook["id"])
    assert [m["email"] for m in lf.members()] == ["sdk@x.com"]


def test_org_scoped_calls_without_an_org_explain_themselves():
    c = LoopForge("http://x", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ValueError, match="needs an organization"):
        c.usage()


def test_wait_for_task_polls_until_terminal_and_times_out():
    states = iter(["PLANNING", "BUILDING", "COMPLETED"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "t", "status": next(states)})

    c = LoopForge("http://x", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert c.wait_for_task("t", poll=0)["status"] == "COMPLETED"
    stuck = LoopForge(
        "http://x",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "BUILDING"})),
        sleep=lambda s: None,
    )
    with pytest.raises(TimeoutError):
        stuck.wait_for_task("t", timeout=0, poll=0)


def test_conflict_and_error_body_without_the_envelope():
    c = LoopForge(
        "http://x",
        transport=httpx.MockTransport(lambda r: httpx.Response(409, json={"detail": "plain"})),
        sleep=lambda s: None,
    )
    with pytest.raises(Conflict) as e:
        c.request("GET", "/x")
    assert e.value.message == "plain"
    text = LoopForge("http://x", transport=httpx.MockTransport(lambda r: httpx.Response(502, text="bad gateway")),
                     sleep=lambda s: None, max_retries=0)  # fmt: skip
    with pytest.raises(APIError) as e2:
        text.request("GET", "/x")
    assert e2.value.status == 502 and "bad gateway" in e2.value.message


def test_app_is_the_one_under_test():
    assert app.title == "LoopForge"
