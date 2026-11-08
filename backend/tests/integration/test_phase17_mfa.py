# ruff: noqa: E501
"""Phase 17: TOTP second factor - RFC 6238 vectors, replay, recovery codes, login step-up, org policy."""

import base64
import time
import uuid

import pytest

from app.database.models import AuditLog, User
from app.services import mfa_service
from tests.conftest import register_and_login

API = "/api/v1"
PASSWORD = "password123"

# RFC 6238 appendix B: ASCII secret "12345678901234567890", SHA-1 (6-digit = low 6 of the 8-digit value)
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_totp_matches_the_rfc_6238_test_vectors(at, expected):
    assert mfa_service.totp_at(RFC_SECRET, at) == expected


def test_provisioning_uri_carries_the_secret_and_issuer():
    uri = mfa_service.provisioning_uri("ABC234", "a@b.co")
    assert uri.startswith("otpauth://totp/LoopForge%3Aa%40b.co?") and "secret=ABC234" in uri


@pytest.fixture
def me(client):
    h = register_and_login(client, "mfa.user@corp.example", PASSWORD)
    org = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return {"h": h, "org": org, "hh": {**h, "X-Org-Id": org}}


def enrol(client, me):
    r = client.post(f"{API}/auth/mfa/enroll", headers=me["h"])
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    code = mfa_service.totp_at(secret, time.time())
    r = client.post(f"{API}/auth/mfa/activate", json={"code": code}, headers=me["h"])
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def login(client, code=None, email="mfa.user@corp.example"):
    data = {"username": email, "password": PASSWORD}
    if code is not None:
        data["mfa_code"] = code
    return client.post(f"{API}/auth/login", data=data)


def stored(client, email="mfa.user@corp.example"):
    with client.factory() as db:
        u = db.query(User).filter_by(email=email).one()
        return u.totp_secret_enc, u.recovery_codes, u.totp_enabled_at, u.totp_last_step


def test_enrol_activate_status_and_the_secret_is_encrypted_at_rest(client, me):
    assert client.get(f"{API}/auth/mfa", headers=me["h"]).json() == {
        "enabled": False, "recovery_codes_left": 0,
    }  # fmt: skip
    secret, codes = enrol(client, me)
    enc, hashes, enabled_at, _ = stored(client)
    assert enc.startswith("v2:") and secret not in enc and enabled_at is not None
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(c not in hashes for c in codes) and len(hashes) == 10  # only hashes are stored
    assert client.get(f"{API}/auth/mfa", headers=me["h"]).json() == {
        "enabled": True, "recovery_codes_left": 10,
    }  # fmt: skip
    assert client.post(f"{API}/auth/mfa/enroll", headers=me["h"]).status_code == 409


def test_activate_needs_a_correct_code_and_a_started_enrolment(client, me):
    r = client.post(f"{API}/auth/mfa/activate", json={"code": "123456"}, headers=me["h"])
    assert r.status_code == 400
    client.post(f"{API}/auth/mfa/enroll", headers=me["h"])
    r = client.post(f"{API}/auth/mfa/activate", json={"code": "000000"}, headers=me["h"])
    assert r.status_code == 400
    assert stored(client)[2] is None  # still not enabled


def test_login_without_mfa_is_unchanged(client, me):
    assert login(client).status_code == 200


def test_login_step_up_requires_a_valid_code(client, me):
    secret, _ = enrol(client, me)
    r = login(client)
    assert r.status_code == 401 and r.headers["x-mfa-required"] == "true"
    assert "access_token" not in r.text
    bad = login(client, "000000")
    assert bad.status_code == 401 and bad.headers["x-mfa-required"] == "true"
    # the step used at activation is spent; the next step's code is valid (the clock-skew window)
    nxt = mfa_service.totp_at(secret, time.time() + 30)
    ok = login(client, nxt)
    assert ok.status_code == 200 and "access_token" in ok.json()
    with client.factory() as db:
        actions = [a.action for a in db.query(AuditLog).order_by(AuditLog.created_at)]
        methods = [
            a.detail.get("method") for a in db.query(AuditLog).filter_by(action="auth.login")
        ]
    assert "auth.login_failed" in actions and "password+totp" in methods


def test_a_code_cannot_be_replayed_and_an_old_one_is_refused(client, me):
    secret, _ = enrol(client, me)
    t = time.time()
    code = mfa_service.totp_at(secret, t + 30)
    assert login(client, code).status_code == 200
    assert login(client, code).status_code == 401  # same step: replay
    assert login(client, mfa_service.totp_at(secret, t)).status_code == 401  # earlier step
    assert login(client, mfa_service.totp_at(secret, t - 300)).status_code == 401  # outside window


def test_a_wrong_password_never_reveals_whether_mfa_is_on(client, me):
    enrol(client, me)
    r = client.post(
        f"{API}/auth/login", data={"username": "mfa.user@corp.example", "password": "nope-nope"}
    )
    assert r.status_code == 401 and "x-mfa-required" not in r.headers


def test_recovery_codes_work_once(client, me):
    _, codes = enrol(client, me)
    assert login(client, codes[0]).status_code == 200
    assert login(client, codes[0]).status_code == 401
    assert len(stored(client)[1]) == 9
    assert login(client, codes[1].upper()).status_code == 200  # case-insensitive


def test_wrong_codes_are_rate_limited_like_wrong_passwords(client, me, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "login_max_attempts", 3)
    enrol(client, me)
    for _ in range(3):
        assert login(client, "000000").status_code == 401
    assert login(client, "000000").status_code == 429


def test_disable_needs_a_code_and_clears_everything(client, me):
    secret, codes = enrol(client, me)
    assert (
        client.post(f"{API}/auth/mfa/disable", json={"code": "000000"}, headers=me["h"]).status_code
        == 400
    )
    r = client.post(f"{API}/auth/mfa/disable", json={"code": codes[0]}, headers=me["h"])
    assert r.status_code == 204
    assert stored(client) == (None, [], None, None)
    assert login(client).status_code == 200
    assert (
        client.post(f"{API}/auth/mfa/disable", json={"code": "123456"}, headers=me["h"]).status_code
        == 409
    )
    with client.factory() as db:
        actions = {a.action for a in db.query(AuditLog)}
    assert {"auth.mfa_enabled", "auth.mfa_disabled", "auth.mfa_failed"} <= actions


def test_org_policy_blocks_users_without_mfa_but_not_api_tokens_or_passwordless(client, me):
    # the admin must enrol first, otherwise they would lock themselves out
    r = client.patch(f"{API}/orgs/{me['org']}", json={"require_mfa": True}, headers=me["hh"])
    assert r.status_code == 409
    secret, _ = enrol(client, me)
    r = client.patch(f"{API}/orgs/{me['org']}", json={"require_mfa": True}, headers=me["hh"])
    assert r.status_code == 200 and r.json()["require_mfa"] is True
    assert (
        client.patch(
            f"{API}/orgs/{me['org']}", json={"require_mfa": None}, headers=me["hh"]
        ).status_code
        == 422
    )

    # a member without MFA is refused with a pointer to enrolment...
    h2 = register_and_login(client, "plain@corp.example", PASSWORD)
    client.post(
        f"{API}/orgs/{me['org']}/members",
        json={"email": "plain@corp.example", "role": "developer"},
        headers=me["hh"],
    )
    blocked = client.get(f"{API}/projects", headers={**h2, "X-Org-Id": me["org"]})
    assert blocked.status_code == 403 and blocked.headers["x-mfa-enrolment-required"] == "true"
    assert (
        client.get(f"{API}/auth/me", headers=h2).status_code == 200
    )  # account-level calls still work
    assert (
        client.post(f"{API}/auth/mfa/enroll", headers=h2).status_code == 200
    )  # and enrolment itself
    # ...the org-path variant too
    assert client.get(f"{API}/orgs/{me['org']}/usage", headers=h2).status_code == 403

    # an enrolled member passes
    assert client.get(f"{API}/projects", headers=me["hh"]).status_code == 200

    # automation tokens are exempt
    tok = client.post(
        f"{API}/orgs/{me['org']}/tokens", json={"name": "ci", "scope": "viewer"}, headers=me["hh"]
    )
    assert tok.status_code == 201, tok.text
    api = {"Authorization": f"Bearer {tok.json()['token']}"}
    assert client.get(f"{API}/projects", headers=api).status_code == 200

    # a passwordless (SSO/SCIM) account is exempt: its identity provider owns authentication
    with client.factory() as db:
        from app.database.models import Membership

        u = User(email="sso@corp.example", password_hash=None, email_verified_at=None)
        u.id = uuid.uuid4()
        db.add(u)
        db.flush()
        db.add(Membership(org_id=uuid.UUID(me["org"]), user_id=u.id, role="viewer"))
        db.commit()
        from app.utils.security import create_access_token

        jwt_ = create_access_token(str(u.id), u.token_version)
    sso = {"Authorization": f"Bearer {jwt_}", "X-Org-Id": me["org"]}
    assert client.get(f"{API}/projects", headers=sso).status_code == 200


def test_cannot_disable_mfa_while_an_org_requires_it(client, me):
    _, codes = enrol(client, me)
    client.patch(f"{API}/orgs/{me['org']}", json={"require_mfa": True}, headers=me["hh"])
    r = client.post(f"{API}/auth/mfa/disable", json={"code": codes[0]}, headers=me["h"])
    assert r.status_code == 409 and "requires MFA" in r.json()["error"]["message"]


def test_mfa_secrets_are_re_encrypted_by_key_rotation(client, me, monkeypatch):
    import json

    from app.config import settings
    from app.services import key_rotation

    k1, k2 = "k1-" + "a" * 40, "k2-" + "b" * 40
    ring = lambda active: json.dumps({"active": active, "keys": {"k1": k1, "k2": k2}})  # noqa: E731
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    secret, _ = enrol(client, me)
    monkeypatch.setattr(settings, "keyring_json", ring("k2"))
    with client.factory() as db:
        assert key_rotation.status(db)["values_by_key"] == {"k1": 1}
        assert key_rotation.rotate(db).rotated == 1
    monkeypatch.setattr(settings, "keyring_json", json.dumps({"active": "k2", "keys": {"k2": k2}}))
    code = mfa_service.totp_at(secret, time.time() + 30)
    assert login(client, code).status_code == 200  # still verifies after the old key is gone
