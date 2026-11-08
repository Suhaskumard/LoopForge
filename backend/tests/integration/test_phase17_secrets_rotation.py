# ruff: noqa: E501
"""Phase 17: webhook secrets: encrypted at rest and rotatable; stored secrets re-encrypt on key change."""

import json
import uuid
from datetime import datetime, timedelta

import httpx
import pytest

from app import keys_cli
from app.config import settings
from app.database.models import OrgIntegration, WebhookEndpoint
from app.services import key_rotation, publish_service
from app.services import webhook_service as ws
from app.utils import keyring
from tests.conftest import register_and_login

API = "/api/v1"
K1 = "k1-" + "a" * 40
K2 = "k2-" + "b" * 40


def ring(active):
    return json.dumps({"active": active, "keys": {"k1": K1, "k2": K2}})


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "webhook_allow_private_hosts", True)
    monkeypatch.setattr(settings, "keyring_json", "")
    monkeypatch.setattr(settings, "secrets_key", "")


def _admin(client):
    h = register_and_login(client, "admin@example.com")
    org = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return org, {**h, "X-Org-Id": org}


def _create(client, org, h):
    r = client.post(f"{API}/orgs/{org}/webhooks", json={"url": "https://hooks.test/in"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _deliver(client, org):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["sig"] = request.content, request.headers[ws.SIGNATURE_HEADER]
        return httpx.Response(204)

    with client.factory() as db:
        ws.emit(db, uuid.UUID(org), "task.completed", {"x": 1})
        ws.deliver_due(db, httpx.Client(transport=httpx.MockTransport(handler)))
    return seen["body"], seen["sig"]


def test_the_signing_secret_is_not_stored_in_the_clear(client):
    org, h = _admin(client)
    ep = _create(client, org, h)
    with client.factory() as db:
        stored = db.get(WebhookEndpoint, uuid.UUID(ep["id"])).secret
    assert stored.startswith("v2:") and ep["secret"] not in stored
    body, sig = _deliver(client, org)
    assert ws.verify_signature(ep["secret"], body, sig)
    listing = client.get(f"{API}/orgs/{org}/webhooks", headers=h).json()
    assert "secret" not in listing[0]


def test_rotation_signs_with_both_secrets_during_the_overlap_then_only_the_new(client, monkeypatch):
    org, h = _admin(client)
    ep = _create(client, org, h)
    old = ep["secret"]
    r = client.post(f"{API}/orgs/{org}/webhooks/{ep['id']}/rotate", headers=h)
    assert r.status_code == 200
    new = r.json()["secret"]
    assert new != old and r.json()["overlap_hours"] == 24

    body, sig = _deliver(client, org)
    assert ws.verify_signature(new, body, sig) and ws.verify_signature(old, body, sig)

    with client.factory() as db:  # push the rotation outside the overlap window
        row = db.get(WebhookEndpoint, uuid.UUID(ep["id"]))
        row.rotated_at = datetime.utcnow() - timedelta(hours=25)
        db.commit()
    body, sig = _deliver(client, org)
    assert ws.verify_signature(new, body, sig) and not ws.verify_signature(old, body, sig)

    actions = [e["action"] for e in client.get(f"{API}/orgs/{org}/audit", headers=h).json()]
    assert "webhook.rotate_secret" in actions


def test_rotation_is_admin_only_and_org_scoped(client):
    org, h = _admin(client)
    ep = _create(client, org, h)
    other = register_and_login(client, "other@example.com")
    org2 = client.get(f"{API}/orgs", headers=other).json()[0]["id"]
    r = client.post(
        f"{API}/orgs/{org2}/webhooks/{ep['id']}/rotate", headers={**other, "X-Org-Id": org2}
    )
    assert r.status_code == 404  # another org's webhook is invisible


def test_a_pre_phase17_plaintext_secret_still_signs(client):
    org, h = _admin(client)
    ep = _create(client, org, h)
    with client.factory() as db:
        db.get(WebhookEndpoint, uuid.UUID(ep["id"])).secret = "whsec_plain"
        db.commit()
    body, sig = _deliver(client, org)
    assert ws.verify_signature("whsec_plain", body, sig)


def test_verify_signature_accepts_any_of_several_v1_values():
    body = b"{}"
    two = ws.sign("a", body, 1000) + "," + ws.sign("b", body, 1000).split(",", 1)[1]
    assert ws.verify_signature("a", body, two, now=1000)
    assert ws.verify_signature("b", body, two, now=1000)
    assert not ws.verify_signature("c", body, two, now=1000)


# ---- key rotation of stored secrets ------------------------------------------------------------


def _seed(client, monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    org, h = _admin(client)
    ep = _create(client, org, h)
    with client.factory() as db:
        publish_service.save_token(db, uuid.UUID(org), "ghp_secret_token")
    return org, ep


def test_rotate_reencrypts_everything_and_is_idempotent(client, monkeypatch, capsys):
    org, ep = _seed(client, monkeypatch)
    monkeypatch.setattr(settings, "keyring_json", ring("k2"))
    with client.factory() as db:
        assert key_rotation.status(db)["values_by_key"] == {"k1": 2}
        dry = key_rotation.rotate(db, dry_run=True)
        assert dry.rotated == 2 and key_rotation.status(db)["values_by_key"] == {"k1": 2}
        rep = key_rotation.rotate(db)
        assert (rep.rotated, rep.already_current, rep.failed) == (2, 0, [])
        assert key_rotation.status(db)["values_by_key"] == {"k2": 2}
        again = key_rotation.rotate(db)
        assert (again.rotated, again.already_current) == (0, 2)
    # the old key can now be dropped from the ring and everything still works
    monkeypatch.setattr(settings, "keyring_json", json.dumps({"active": "k2", "keys": {"k2": K2}}))
    with client.factory() as db:
        assert publish_service._token(db, uuid.UUID(org)) == "ghp_secret_token"
    body, sig = _deliver(client, org)
    assert ws.verify_signature(ep["secret"], body, sig)


def test_rotate_migrates_plaintext_webhook_secrets(client, monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    org, h = _admin(client)
    ep = _create(client, org, h)
    with client.factory() as db:
        db.get(WebhookEndpoint, uuid.UUID(ep["id"])).secret = "whsec_plain"
        db.commit()
        assert key_rotation.rotate(db).rotated == 1
        stored = db.get(WebhookEndpoint, uuid.UUID(ep["id"])).secret
        assert keyring.decrypt(stored) == "whsec_plain"


def test_values_under_a_missing_key_are_reported_not_destroyed(client, monkeypatch):
    org, ep = _seed(client, monkeypatch)
    monkeypatch.setattr(settings, "keyring_json", json.dumps({"active": "k2", "keys": {"k2": K2}}))
    with client.factory() as db:
        before = db.query(OrgIntegration).one().token_enc
        rep = key_rotation.rotate(db)
        assert len(rep.failed) == 2 and rep.rotated == 0
        assert db.query(OrgIntegration).one().token_enc == before
        with pytest.raises(publish_service.PublishError, match="cannot be decrypted"):
            publish_service._token(db, uuid.UUID(org))


def test_keys_cli_reports_json_and_exit_codes(client, monkeypatch, capsys):
    _seed(client, monkeypatch)
    monkeypatch.setattr(settings, "keyring_json", ring("k2"))
    monkeypatch.setattr(keys_cli, "SessionLocal", client.factory)
    assert keys_cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["values_by_key"] == {"k1": 2}
    assert keys_cli.main(["rotate", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["rotated"] == 2
    assert keys_cli.main(["rotate"]) == 0
    assert json.loads(capsys.readouterr().out)["rotated"] == 2
    monkeypatch.setattr(settings, "keyring_json", json.dumps({"active": "k1", "keys": {"k1": K1}}))
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    # values are under k2 and k2 is still in this ring -> nothing failed, k1 active -> re-rotates
    assert keys_cli.main(["rotate"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(settings, "keyring_json", json.dumps({"active": "k1", "keys": {"k1": K1}}))
    assert keys_cli.main(["rotate", "--dry-run"]) == 0  # all under k1 now
