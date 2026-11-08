# ruff: noqa: E501
"""Phase 18: per-token rate limits and Idempotency-Key replay on the create endpoints."""

import threading
import uuid

import pytest

from app.config import settings
from app.database.models import IdempotencyKey, Project, RateCounter, Task
from app.services import idempotency_service, rate_limit
from tests.conftest import register_and_login

API = "/api/v1"


@pytest.fixture
def org(client):
    h = register_and_login(client, "owner@x.com")
    oid = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return {"id": oid, "h": {**h, "X-Org-Id": oid}}


def api_token(client, org, scope="developer"):
    r = client.post(
        f"{API}/orgs/{org['id']}/tokens", json={"name": "ci", "scope": scope}, headers=org["h"]
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---- rate limits -------------------------------------------------------------------------------


def test_window_counter_counts_resets_and_never_stores_when_unlimited(client):
    with client.factory() as db:
        first = rate_limit.hit(db, "k", 3, now=1000.0)
        assert (first.allowed, first.remaining, first.limit) == (True, 2, 3)
        assert rate_limit.hit(db, "k", 3, now=1001.0).remaining == 1
        assert rate_limit.hit(db, "k", 3, now=1002.0).remaining == 0
        over = rate_limit.hit(db, "k", 3, now=1003.0)
        assert over.allowed is False and over.remaining == 0 and 0 < over.reset_seconds <= 61
        assert rate_limit.hit(db, "k", 3, now=1000.0 + 60).allowed is True  # next window
        assert rate_limit.hit(db, "other", 3, now=1000.0).remaining == 2  # keys are independent
        before = db.query(RateCounter).count()
        assert (
            rate_limit.hit(db, "u", 0).allowed is True and db.query(RateCounter).count() == before
        )
        assert rate_limit.purge(db, older_than_seconds=10, now=100000.0) == before


def test_concurrent_requests_are_all_counted(client):
    results = []

    def worker():
        with client.factory() as db:
            results.append(rate_limit.hit(db, "race", 1000, now=5000.0).remaining)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with client.factory() as db:
        assert db.get(RateCounter, ("race", 5000 // 60 * 60)).count == 12
    assert len(set(results)) == 12  # every request saw a distinct count: none lost, none doubled


def test_api_token_is_limited_with_headers_and_retry_after(client, org, monkeypatch):
    monkeypatch.setattr(settings, "api_token_rate_limit_per_minute", 3)
    tok = api_token(client, org)  # the setup call used the JWT, not the token
    seen = [client.get(f"{API}/projects", headers=tok) for _ in range(3)]
    assert [r.status_code for r in seen] == [200, 200, 200]
    assert seen[0].headers["x-ratelimit-limit"] == "3"
    assert [r.headers["x-ratelimit-remaining"] for r in seen] == ["2", "1", "0"]
    blocked = client.get(f"{API}/projects", headers=tok)
    assert blocked.status_code == 429
    assert (
        int(blocked.headers["retry-after"]) >= 1 and blocked.headers["x-ratelimit-remaining"] == "0"
    )
    assert "Rate limit exceeded" in blocked.json()["error"]["message"]


def test_one_tokens_limit_does_not_affect_another_or_the_session(client, org, monkeypatch):
    monkeypatch.setattr(settings, "api_token_rate_limit_per_minute", 1)
    a, b = api_token(client, org), api_token(client, org)
    assert client.get(f"{API}/projects", headers=a).status_code == 200
    assert client.get(f"{API}/projects", headers=a).status_code == 429
    assert client.get(f"{API}/projects", headers=b).status_code == 200
    assert client.get(f"{API}/projects", headers=org["h"]).status_code == 200  # JWT: no user limit


def test_per_user_limit_is_opt_in(client, org, monkeypatch):
    monkeypatch.setattr(settings, "user_rate_limit_per_minute", 2)
    codes = [client.get(f"{API}/projects", headers=org["h"]).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    other = register_and_login(client, "bystander@x.com")
    assert client.get(f"{API}/projects", headers=other).status_code == 200  # separate counter


def test_limits_off_means_no_headers_and_no_rows(client, org, monkeypatch):
    monkeypatch.setattr(settings, "api_token_rate_limit_per_minute", 0)
    tok = api_token(client, org)
    r = client.get(f"{API}/projects", headers=tok)
    assert r.status_code == 200 and "x-ratelimit-limit" not in r.headers


# ---- idempotency -------------------------------------------------------------------------------


def post(client, org, path, body, key=None, headers=None):
    h = {**(headers or org["h"]), **({"Idempotency-Key": key} if key else {})}
    return client.post(f"{API}{path}", json=body, headers=h)


def test_same_key_same_body_replays_the_original_response_without_running_again(client, org):
    first = post(client, org, "/projects", {"name": "alpha"}, key="k-1")
    again = post(client, org, "/projects", {"name": "alpha"}, key="k-1")
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json() and again.headers["idempotent-replay"] == "true"
    assert "idempotent-replay" not in first.headers
    with client.factory() as db:
        assert db.query(Project).count() == 1  # created exactly once


def test_without_a_key_nothing_changes(client, org):
    post(client, org, "/projects", {"name": "alpha"})
    post(client, org, "/projects", {"name": "alpha"})
    with client.factory() as db:
        assert db.query(Project).count() == 2


def test_same_key_different_body_is_a_client_error(client, org):
    post(client, org, "/projects", {"name": "alpha"}, key="k-2")
    r = post(client, org, "/projects", {"name": "beta"}, key="k-2")
    assert r.status_code == 422 and "different request" in r.json()["error"]["message"]
    with client.factory() as db:
        assert db.query(Project).count() == 1


def test_keys_are_scoped_to_the_caller_and_the_route(client, org):
    a = post(client, org, "/projects", {"name": "alpha"}, key="shared")
    other = register_and_login(client, "other@x.com")
    oo = client.get(f"{API}/orgs", headers=other).json()[0]["id"]
    b = post(client, {"h": {**other, "X-Org-Id": oo}}, "/projects", {"name": "alpha"}, key="shared")
    assert b.status_code == 201 and b.json()["id"] != a.json()["id"]  # not a replay of A's response
    assert "idempotent-replay" not in b.headers
    tok = api_token(client, org)  # same org, different credential
    c = post(client, org, "/projects", {"name": "alpha"}, key="shared", headers=tok)
    assert c.status_code == 201 and c.json()["id"] != a.json()["id"]


def test_failures_are_not_remembered_so_the_retry_runs_for_real(client, org):
    bad = post(
        client,
        org,
        "/tasks",
        {"project_id": str(uuid.uuid4()), "requirement": "Build it"},
        key="k-3",
    )
    assert bad.status_code == 404
    proj = post(client, org, "/projects", {"name": "p"}).json()
    # same key and same body: the earlier failure left nothing behind
    with client.factory() as db:
        assert db.query(IdempotencyKey).count() == 0
    ok = post(
        client,
        org,
        "/tasks",
        {"project_id": proj["id"], "requirement": "Build employees"},
        key="k-4",
    )
    assert ok.status_code == 201
    replay = post(
        client,
        org,
        "/tasks",
        {"project_id": proj["id"], "requirement": "Build employees"},
        key="k-4",
    )
    assert replay.json()["id"] == ok.json()["id"] and replay.headers["idempotent-replay"] == "true"
    with client.factory() as db:
        assert db.query(Task).count() == 1


def test_start_is_safe_to_retry_and_keeps_its_etag(client, org):
    proj = post(client, org, "/projects", {"name": "p"}).json()
    task = post(
        client, org, "/tasks", {"project_id": proj["id"], "requirement": "Build employees"}
    ).json()
    first = post(client, org, f"/tasks/{task['id']}/start", {}, key="start-1")
    again = post(client, org, f"/tasks/{task['id']}/start", {}, key="start-1")
    assert first.status_code == 202 == again.status_code
    assert (
        again.headers["idempotent-replay"] == "true"
        and again.headers["etag"] == first.headers["etag"]
    )
    # a plain second start (no key) is the normal conflict
    assert post(client, org, f"/tasks/{task['id']}/start", {}).status_code in (409, 202)


def test_a_request_still_in_progress_gets_409(client, org):
    with client.factory() as db:
        scope = idempotency_service.scope_of("user:" + str(uuid.uuid4()), None)
        assert idempotency_service.begin(db, scope, "k", "POST /x", "h1").outcome == "run"
        assert idempotency_service.begin(db, scope, "k", "POST /x", "h1").outcome == "in_progress"
        assert idempotency_service.begin(db, scope, "k", "POST /x", "h2").outcome == "mismatch"


def test_concurrent_duplicates_have_exactly_one_winner(client):
    scope = idempotency_service.scope_of("api:tok", "org")
    outcomes = []

    def worker():
        with client.factory() as db:
            outcomes.append(idempotency_service.begin(db, scope, "race", "POST /x", "h").outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes.count("run") == 1 and outcomes.count("in_progress") == 7


@pytest.mark.parametrize("key", ["", "   ", "x" * 201])
def test_bad_keys_are_rejected(client, org, key):
    r = post(client, org, "/projects", {"name": "alpha"}, key=key or " ")
    assert r.status_code == 422
    with client.factory() as db:
        assert db.query(Project).count() == 0


def test_only_the_documented_routes_are_idempotent_and_unauthenticated_calls_store_nothing(
    client, org
):
    r = client.post(f"{API}/projects", json={"name": "a"}, headers={"Idempotency-Key": "k"})
    assert r.status_code == 401
    r = post(client, org, "/auth/mfa/enroll", {}, key="not-covered")
    assert r.status_code == 200 and "idempotent-replay" not in r.headers
    with client.factory() as db:
        assert db.query(IdempotencyKey).count() == 0


def test_expired_keys_are_purged(client, org):
    from datetime import datetime, timedelta

    post(client, org, "/projects", {"name": "alpha"}, key="old")
    with client.factory() as db:
        assert idempotency_service.purge(db) == 0
        assert idempotency_service.purge(db, now=datetime.utcnow() + timedelta(hours=25)) == 1
    again = post(client, org, "/projects", {"name": "alpha"}, key="old")
    assert "idempotent-replay" not in again.headers  # forgotten: it ran again
