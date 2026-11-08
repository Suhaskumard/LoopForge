"""Phase 11: scoped API tokens."""

import uuid
from datetime import datetime, timedelta

from app.database.models import ApiToken
from app.utils.redact import redact, scan_secrets
from tests.conftest import register_and_login

API = "/api/v1"


def _admin(client):
    h = register_and_login(client, "admin@example.com")
    org = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return org, {**h, "X-Org-Id": org}


def _token(client, org, h, scope="developer", **extra):
    r = client.post(
        f"{API}/orgs/{org}/tokens", json={"name": "ci", "scope": scope, **extra}, headers=h
    )
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok['token']}"}


def test_token_authenticates_and_is_capped_by_scope(client):
    org, h = _admin(client)
    viewer = _token(client, org, h, "viewer")
    dev = _token(client, org, h, "developer")
    assert client.get(f"{API}/projects", headers=_bearer(viewer)).status_code == 200
    assert (
        client.post(f"{API}/projects", json={"name": "x"}, headers=_bearer(viewer)).status_code
        == 403
    )
    assert (
        client.post(f"{API}/projects", json={"name": "x"}, headers=_bearer(dev)).status_code == 201
    )
    # owner is admin, but the token never is
    assert client.get(f"{API}/orgs/{org}/tokens", headers=_bearer(dev)).status_code == 403
    assert (
        client.post(
            f"{API}/orgs/{org}/tokens", json={"name": "n"}, headers=_bearer(dev)
        ).status_code
        == 403
    )


def test_token_is_bound_to_its_organization(client):
    org, h = _admin(client)
    tok = _token(client, org, h)
    other_org = client.post(f"{API}/orgs", json={"name": "second"}, headers=h).json()["id"]
    assert (
        client.get(f"{API}/projects", headers={**_bearer(tok), "X-Org-Id": other_org}).status_code
        == 403
    )
    assert client.get(f"{API}/orgs/{other_org}", headers=_bearer(tok)).status_code == 404
    assert client.get(f"{API}/orgs/{org}", headers=_bearer(tok)).status_code == 200


def test_revoked_expired_and_garbage_tokens_are_rejected(client):
    org, h = _admin(client)
    tok = _token(client, org, h)
    expiring = _token(client, org, h, expires_days=1)
    assert client.get(f"{API}/projects", headers=_bearer(tok)).status_code == 200
    assert client.delete(f"{API}/orgs/{org}/tokens/{tok['id']}", headers=h).status_code == 204
    assert client.get(f"{API}/projects", headers=_bearer(tok)).status_code == 401
    with client.factory() as db:
        db.get(ApiToken, uuid.UUID(expiring["id"])).expires_at = datetime.utcnow() - timedelta(1)
        db.commit()
    assert client.get(f"{API}/projects", headers=_bearer(expiring)).status_code == 401
    bad = {"Authorization": "Bearer lfk_" + "x" * 40}
    assert client.get(f"{API}/projects", headers=bad).status_code == 401


def test_only_the_hash_is_stored_and_secret_is_shown_once(client):
    org, h = _admin(client)
    tok = _token(client, org, h)
    with client.factory() as db:
        row = db.get(ApiToken, uuid.UUID(tok["id"]))
        assert tok["token"] not in (row.token_hash, row.prefix) and len(row.prefix) == 8
    listed = client.get(f"{API}/orgs/{org}/tokens", headers=h).json()
    assert "token" not in listed[0] and listed[0]["last_used_at"] is None
    client.get(f"{API}/projects", headers=_bearer(tok))
    assert client.get(f"{API}/orgs/{org}/tokens", headers=h).json()[0]["last_used_at"]


def test_token_calls_are_audited_with_the_token_id(client):
    org, h = _admin(client)
    tok = _token(client, org, h)
    project = client.post(f"{API}/projects", json={"name": "x"}, headers=_bearer(tok)).json()
    r = client.post(
        f"{API}/tasks",
        json={"project_id": project["id"], "requirement": "Build a thing with tests."},
        headers=_bearer(tok),
    )
    assert r.status_code == 201, r.text
    entries = client.get(f"{API}/orgs/{org}/audit", headers=h).json()
    created = [e for e in entries if e["action"] == "task.create"]
    assert created and created[0]["detail"]["api_token"] == tok["id"]


def test_tokens_are_redacted_everywhere():
    secret = "lfk_" + "A1b2C3d4" * 5
    assert secret not in redact(f"curl -H 'X: {secret}'")
    assert "LoopForge API token" in scan_secrets("a.py", f"x = '{secret}'")
