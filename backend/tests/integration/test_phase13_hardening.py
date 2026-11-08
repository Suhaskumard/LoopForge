# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: login-failure auditing, per-model prices, worker metrics token, backup encryption."""

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.database.models import AgentRun, Iteration, User
from app.services import analytics_service
from app.utils import metrics_server
from tests.conftest import register_and_login
from tests.integration.test_phase7_scale import _task

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]


def _admin(client, email):
    h = register_and_login(client, email)
    org = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return h, org


def _audit(client, h, org, action):
    return client.get(f"{API}/orgs/{org}/audit", params={"action": action}, headers=h).json()


# ---- login failures are audited (without becoming a way to flood the log) ---------------------------------------


def test_a_failed_login_for_a_real_account_is_audited_without_the_email_in_clear(client):
    h, org = _admin(client, "victim@example.com")
    r = client.post(
        f"{API}/auth/login", data={"username": "victim@example.com", "password": "wrong-pass-1"}
    )
    assert r.status_code == 401
    rows = _audit(client, h, org, "auth.login_failed")
    assert len(rows) == 1 and rows[0]["detail"]["reason"] == "bad_password"
    assert (
        rows[0]["detail"]["email_sha256"] == hashlib.sha256(b"victim@example.com").hexdigest()[:16]
    )
    assert "victim@example.com" not in json.dumps(rows[0])  # a hash, not the address


def test_unknown_addresses_are_not_written_so_the_log_cannot_be_flooded(client):
    h, org = _admin(client, "real@example.com")
    for i in range(8):
        client.post(
            f"{API}/auth/login", data={"username": f"nobody{i}@example.com", "password": "x" * 9}
        )
    assert _audit(client, h, org, "auth.login_failed") == []


def test_an_sso_only_account_is_reported_as_such(client):
    h, org = _admin(client, "sso@example.com")
    with client.factory() as db:
        db.query(User).filter_by(email="sso@example.com").one().password_hash = None
        db.commit()
    assert (
        client.post(
            f"{API}/auth/login", data={"username": "sso@example.com", "password": "anything1"}
        ).status_code
        == 401
    )
    assert _audit(client, h, org, "auth.login_failed")[0]["detail"]["reason"] == "sso_only"


def test_being_rate_limited_is_audited(client, monkeypatch):
    monkeypatch.setattr(settings, "login_max_attempts", 3)
    h, org = _admin(client, "locked@example.com")
    for _ in range(3):
        client.post(
            f"{API}/auth/login", data={"username": "locked@example.com", "password": "wrong-pass-1"}
        )
    blocked = client.post(
        f"{API}/auth/login", data={"username": "locked@example.com", "password": "password123"}
    )
    assert blocked.status_code == 429
    assert len(_audit(client, h, org, "auth.login_failed")) == 3
    assert (
        _audit(client, h, org, "auth.login_blocked")[0]["detail"]["reason"] == "too_many_failures"
    )


def test_replaying_a_spent_refresh_token_is_audited_and_kills_the_session(client):
    client.post(
        f"{API}/auth/register", json={"email": "thief@example.com", "password": "password123"}
    )
    login = client.post(
        f"{API}/auth/login", data={"username": "thief@example.com", "password": "password123"}
    ).json()
    old, access = login["refresh_token"], login["access_token"]
    fresh = client.post(f"{API}/auth/refresh", json={"refresh_token": old}).json()
    assert (
        client.post(f"{API}/auth/refresh", json={"refresh_token": old}).status_code == 401
    )  # replay
    assert (
        client.post(
            f"{API}/auth/refresh", json={"refresh_token": fresh["refresh_token"]}
        ).status_code
        == 401
    )
    h = {"Authorization": f"Bearer {access}"}
    org = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    rows = _audit(client, h, org, "auth.refresh_reuse")
    # two signals: the replayed token, then the newer token of the (now revoked) family being presented
    assert len(rows) == 2 and all("revoked" in r["detail"]["note"] for r in rows)


def test_a_plain_invalid_refresh_token_is_not_a_theft_signal(client):
    h, org = _admin(client, "plain@example.com")
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": "garbage"}).status_code == 401
    assert _audit(client, h, org, "auth.refresh_reuse") == []


# ---- per-model prices --------------------------------------------------------------------------------------------


@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setattr(settings, "cost_per_1k_tokens", 0.002)
    monkeypatch.setattr(settings, "model_prices_json", '{"strong": 0.01, "cheap": 0.0005}')


def test_each_model_is_priced_at_its_own_rate_and_others_at_the_default(prices):
    assert analytics_service.cost_of(1000, "strong") == pytest.approx(0.01)
    assert analytics_service.cost_of(2000, "cheap") == pytest.approx(0.001)
    assert analytics_service.cost_of(1000, "unlisted") == pytest.approx(0.002)
    assert analytics_service.cost_of(1000, None) == pytest.approx(0.002)
    assert analytics_service.cost_of(1000) == pytest.approx(0.002)  # the old signature still works


def test_without_prices_everything_behaves_exactly_as_before(monkeypatch):
    monkeypatch.setattr(settings, "model_prices_json", "")
    assert (
        settings.model_prices() == {}
        and settings.price_per_1k("strong") == settings.cost_per_1k_tokens
    )


@pytest.mark.parametrize(
    "bad", ["not json", "[1, 2]", '{"m": "free"}', '{"m": -1}', '{"m": true}', "{"]
)
def test_invalid_price_maps_are_refused_at_startup(bad):
    with pytest.raises(ValueError, match="MODEL_PRICES_JSON"):
        Settings(model_prices_json=bad)


def test_analytics_and_reports_price_each_run_at_its_models_rate(client, prices):
    h = register_and_login(client, "price@example.com")
    task = _task(client, h)
    with client.factory() as db:
        it = Iteration(task_id=uuid.UUID(task["id"]), iteration_number=1)
        db.add(it)
        db.flush()
        for agent, model, tokens in (
            ("Planner", "cheap", 2000),
            ("Repair", "strong", 1000),
            ("Builder", None, 1000),
        ):
            db.add(AgentRun(iteration_id=it.id, agent_name=agent, model=model, tokens_used=tokens))
        db.commit()
    expected = 2000 / 1000 * 0.0005 + 1000 / 1000 * 0.01 + 1000 / 1000 * 0.002  # = 0.013
    assert client.get(f"{API}/analytics/overview", headers=h).json()["total_cost"] == pytest.approx(
        expected
    )
    task_stats = client.get(f"{API}/analytics/tasks/{task['id']}", headers=h).json()
    assert (
        task_stats["estimated_cost"] == pytest.approx(expected)
        and task_stats["total_tokens"] == 4000
    )
    report = client.get(f"{API}/tasks/{task['id']}/report", headers=h).json()
    assert report["estimated_cost"] == pytest.approx(expected) and report["total_tokens"] == 4000


# ---- the worker metrics port can require a token ----------------------------------------------------------------------


def _get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, ""


def test_the_worker_metrics_port_demands_its_token_when_one_is_set():
    server = metrics_server.start(0, host="127.0.0.1", token="scrape-me")
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/metrics"
        assert _get(url)[0] == 401
        assert _get(url, "wrong")[0] == 401
        code, body = _get(url, "scrape-me")
        assert code == 200 and "loopforge_" in body
        assert _get(url.replace("/metrics", "/other"), "scrape-me")[0] == 404
    finally:
        server.shutdown()


def test_without_a_token_the_worker_port_stays_open_as_before():
    server = metrics_server.start(0, host="127.0.0.1")
    try:
        assert _get(f"http://127.0.0.1:{server.server_address[1]}/metrics")[0] == 200
    finally:
        server.shutdown()


# ---- backup encryption (SQLite drill; the PostgreSQL scripts are covered in test_phase13_backup_scripts) -------------


def test_the_encrypted_backup_drill_refuses_a_missing_or_wrong_key_and_leaves_no_plaintext():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backup_drill.py"), "--encrypt"],
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-2500:] + r.stderr[-500:]
    assert "BACKUP DRILL: PASS (encrypted, wrong/missing key refused" in r.stdout
    assert (
        "restore with no key refused" in r.stdout and "restore with a wrong key refused" in r.stdout
    )
    assert "plaintext" not in r.stdout.lower().replace(
        "no plaintext", ""
    )  # no plaintext-leak finding was printed
