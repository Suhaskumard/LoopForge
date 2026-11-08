"""Phase 11 gate: webhook signing, SSRF guard, delivery and retry."""

import json
import uuid
from datetime import datetime, timedelta

import httpx
import pytest

from app.config import settings
from app.database.models import WebhookDelivery
from app.services import webhook_service as ws
from tests.conftest import register_and_login

API = "/api/v1"
SECRET = "whsec_test"
BODY = b'{"event":"task.completed"}'


# ---- signing (pure) ----------------------------------------------------------------------------


def test_signature_known_vector():
    # HMAC-SHA256("whsec_test", "1700000000." + body); recomputed independently of the module
    import hashlib
    import hmac

    expected = hmac.new(SECRET.encode(), b"1700000000." + BODY, hashlib.sha256).hexdigest()
    assert ws.sign(SECRET, BODY, 1700000000) == f"t=1700000000,v1={expected}"


def test_verify_accepts_valid_and_rejects_tampering():
    header = ws.sign(SECRET, BODY, 1000)
    assert ws.verify_signature(SECRET, BODY, header, now=1010)
    assert not ws.verify_signature(SECRET, BODY + b" ", header, now=1010)  # body changed
    assert not ws.verify_signature("other", BODY, header, now=1010)  # wrong secret
    assert not ws.verify_signature(SECRET, BODY, header.replace("v1=", "v1=0"), now=1010)


def test_verify_rejects_replays_outside_the_window():
    header = ws.sign(SECRET, BODY, 1000)
    assert ws.verify_signature(SECRET, BODY, header, now=1000 + 299)
    assert not ws.verify_signature(SECRET, BODY, header, now=1000 + 301)
    assert not ws.verify_signature(SECRET, BODY, header, now=1000 - 301)


@pytest.mark.parametrize("header", ["", "garbage", "t=abc,v1=00", "t=1", "v1=00"])
def test_verify_rejects_malformed_headers(header):
    assert not ws.verify_signature(SECRET, BODY, header, now=1)


# ---- SSRF guard --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "https://user:pw@example.com/hook",
        "https://127.0.0.1/hook",
        "https://localhost/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5/hook",
        "https://[::1]/hook",
    ],
)
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(ws.WebhookUrlError):
        ws.validate_url(url)


# ---- API + delivery ----------------------------------------------------------------------------


@pytest.fixture
def private_ok(monkeypatch):
    monkeypatch.setattr(settings, "webhook_allow_private_hosts", True)


def _admin(client):
    h = register_and_login(client, "admin@example.com")
    org = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return org, {**h, "X-Org-Id": org}


def _create(client, org, h, **kw):
    r = client.post(
        f"{API}/orgs/{org}/webhooks", json={"url": "https://hooks.test/in", **kw}, headers=h
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_rejects_private_target_by_default(client):
    org, h = _admin(client)
    r = client.post(f"{API}/orgs/{org}/webhooks", json={"url": "https://127.0.0.1/x"}, headers=h)
    assert r.status_code == 422
    r = client.post(
        f"{API}/orgs/{org}/webhooks",
        json={"url": "https://hooks.test/x", "events": ["nope"]},
        headers=h,
    )
    assert r.status_code == 422


def test_delivery_is_signed_and_verifiable(client, private_ok):
    org, h = _admin(client)
    ep = _create(client, org, h)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["sig"] = request.content, request.headers[ws.SIGNATURE_HEADER]
        seen["event"] = request.headers["X-LoopForge-Event"]
        return httpx.Response(204)

    with client.factory() as db:
        assert ws.emit(db, uuid.UUID(org), "task.completed", {"task_id": "t1"}) == 1
        assert ws.deliver_due(db, httpx.Client(transport=httpx.MockTransport(handler))) == 1
        d = db.query(WebhookDelivery).one()
        assert d.status == "delivered" and d.response_status == 204 and d.attempts == 1
    assert ws.verify_signature(ep["secret"], seen["body"], seen["sig"])
    assert (
        json.loads(seen["body"])["data"] == {"task_id": "t1"} and seen["event"] == "task.completed"
    )


def test_failed_delivery_retries_with_backoff_then_gives_up(client, private_ok, monkeypatch):
    org, h = _admin(client)
    _create(client, org, h)
    monkeypatch.setattr(settings, "webhook_max_attempts", 3)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with client.factory() as db:
        ws.emit(db, uuid.UUID(org), "task.failed", {})
        d = db.query(WebhookDelivery).one()
        ws.deliver(db, d, http)
        assert d.status == "pending" and d.attempts == 1 and d.last_error == "HTTP 500"
        first_wait = d.next_attempt_at - datetime.utcnow()
        assert timedelta(seconds=20) < first_wait <= timedelta(seconds=31)
        assert ws.deliver_due(db, http) == 0  # not due yet
        ws.deliver(db, d, http)
        assert d.attempts == 2 and d.next_attempt_at - datetime.utcnow() > timedelta(seconds=50)
        ws.deliver(db, d, http)
        assert d.status == "failed" and d.attempts == 3


def test_network_error_is_recorded_without_leaking(client, private_ok):
    org, h = _admin(client)
    _create(client, org, h)

    def boom(request):
        raise httpx.ConnectError("dns secret.internal failed")

    with client.factory() as db:
        ws.emit(db, uuid.UUID(org), "ping", {})
        d = ws.deliver(
            db, db.query(WebhookDelivery).one(), httpx.Client(transport=httpx.MockTransport(boom))
        )
        assert d.last_error == "ConnectError"


def test_event_filter_org_scope_and_secret_redaction(client, private_ok):
    org, h = _admin(client)
    _create(client, org, h, events=["task.completed"])
    other = register_and_login(client, "o@example.com")
    other_org = client.get(f"{API}/orgs", headers=other).json()[0]["id"]
    with client.factory() as db:
        assert ws.emit(db, uuid.UUID(org), "task.failed", {}) == 0  # not subscribed
        assert ws.emit(db, uuid.UUID(other_org), "task.completed", {}) == 0  # other org
        ws.emit(db, uuid.UUID(org), "task.completed", {"note": "key sk-" + "a" * 30})
        assert "sk-aaaa" not in json.dumps(db.query(WebhookDelivery).one().payload)


def test_slack_format(client, private_ok):
    org, h = _admin(client)
    _create(client, org, h, format="slack")
    got = {}

    def handler(request):
        got["body"] = json.loads(request.content)
        return httpx.Response(200)

    with client.factory() as db:
        ws.emit(db, uuid.UUID(org), "task.completed", {"status": "COMPLETED"})
        ws.deliver_due(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert "task.completed" in got["body"]["text"] and "COMPLETED" in got["body"]["text"]


def test_test_endpoint_delete_and_isolation(client, private_ok, monkeypatch):
    org, h = _admin(client)
    ep = _create(client, org, h)
    real = httpx.Client
    monkeypatch.setattr(
        ws.httpx,
        "Client",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )
    r = client.post(f"{API}/orgs/{org}/webhooks/{ep['id']}/test", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "delivered"
    assert (
        len(client.get(f"{API}/orgs/{org}/webhooks/{ep['id']}/deliveries", headers=h).json()) == 1
    )
    stranger = register_and_login(client, "s@example.com")
    assert client.get(f"{API}/orgs/{org}/webhooks", headers=stranger).status_code == 404
    other_org = client.get(f"{API}/orgs", headers=stranger).json()[0]["id"]
    assert (
        client.delete(f"{API}/orgs/{other_org}/webhooks/{ep['id']}", headers=stranger).status_code
        == 404
    )
    assert client.delete(f"{API}/orgs/{org}/webhooks/{ep['id']}", headers=h).status_code == 204
    with client.factory() as db:
        assert ws.emit(db, uuid.UUID(org), "task.completed", {}) == 0  # disabled


def test_terminal_task_queues_a_webhook(client, private_ok):
    org, h = _admin(client)
    _create(client, org, h)
    from app.database.models import Task
    from app.services import run_service

    project = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    task = client.post(
        f"{API}/tasks",
        json={"project_id": project["id"], "requirement": "Build a thing with tests."},
        headers=h,
    ).json()
    with client.factory() as db:
        db.get(Task, uuid.UUID(task["id"])).status = "COMPLETED"
        db.commit()
    # inline mode would try a real HTTP call: queue only, then inspect
    from app.config import settings as s

    s.run_mode = "queue"
    try:
        run_service._notify_terminal(client.factory, uuid.UUID(task["id"]))
    finally:
        s.run_mode = "inline"
    with client.factory() as db:
        d = db.query(WebhookDelivery).one()
        assert d.event == "task.completed" and d.payload["data"]["task_id"] == task["id"]
