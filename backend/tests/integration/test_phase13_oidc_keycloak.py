# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: OIDC login against a REAL Keycloak (the realm in tests/fixtures/keycloak is imported on start).

`tests/integration/test_phase10_oidc.py` proves the verification logic against a scripted provider; this proves it
against a real one: real discovery document, real JWKS, real RS256 signatures, real consent-free login form.
Skipped unless KEYCLOAK_URL is set; `scripts/test_keycloak.sh` starts Keycloak and runs it (a skip is a failure there).

The browser is simulated with httpx: GET /auth/sso/login -> follow the redirect to Keycloak's authorize endpoint ->
post the credentials to the real login form -> take the redirect back to /auth/sso/callback.
"""

import html
import os
import re
import urllib.parse

import httpx
import pytest

from app.config import settings
from app.database.models import User
from app.services import oidc_service

pytestmark = [
    pytest.mark.keycloak,
    pytest.mark.skipif(not os.environ.get("KEYCLOAK_URL"), reason="needs a real Keycloak"),
]

API = "/api/v1"
KC = os.environ.get("KEYCLOAK_URL", "http://localhost:8180")
ISSUER = f"{KC}/realms/loopforge"
REDIRECT = "http://testserver/api/v1/auth/sso/callback"
USERS = {
    "alice": ("alice-pass-123", "alice@corp.example"),
    "bob": ("bob-pass-123", "bob@corp.example"),  # email NOT verified
    "carol": ("carol-pass-123", "carol@other.example"),  # verified, other domain
}


@pytest.fixture(autouse=True)
def real_provider(monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", "loopforge")
    monkeypatch.setattr(settings, "oidc_client_secret", "keycloak-test-secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", REDIRECT)
    monkeypatch.setattr(settings, "oidc_allowed_domains", "")
    monkeypatch.setattr(settings, "sso_frontend_url", "http://app.example/login")
    oidc_service.clear_cache()
    yield
    oidc_service.clear_cache()


def keycloak_login(authorize_url: str, username: str, password: str) -> httpx.Response:
    """Act as the browser: load the login page, submit the form, return Keycloak's (unfollowed) answer."""
    with httpx.Client(follow_redirects=True, timeout=30) as browser:
        page = browser.get(authorize_url)
        assert page.status_code == 200, page.text[:300]
        action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
        assert action, "Keycloak's login form was not found"
        browser.follow_redirects = False
        # Keycloak marks its session cookies `Secure`; a browser treats http://localhost as secure, httpx
        # does not, so send them explicitly (this is what the browser would do).
        cookies = "; ".join(f"{c.name}={c.value}" for c in browser.cookies.jar)
        return browser.post(
            html.unescape(action.group(1)),
            data={"username": username, "password": password, "credentialId": ""},
            headers={"Cookie": cookies},
        )


def sso_round_trip(client, username: str, password: str):
    """Full flow; returns (callback response or None, keycloak login response)."""
    start = client.get(f"{API}/auth/sso/login", follow_redirects=False)
    assert start.status_code == 302 and start.headers["location"].startswith(
        f"{ISSUER}/protocol/openid-connect/auth"
    )
    cookie = start.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    login = keycloak_login(start.headers["location"], username, password)
    if login.status_code != 302:  # wrong password: Keycloak re-renders the form
        return None, login
    location = login.headers["location"]
    assert location.startswith(REDIRECT), location
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))
    client.cookies.clear()
    callback = client.get(
        f"{API}/auth/sso/callback",
        params={"code": query["code"], "state": query["state"]},
        headers={"cookie": f"lf_sso={cookie}"},
        follow_redirects=False,
    )
    return callback, login


def fragment(response) -> dict:
    assert response.status_code == 302
    return dict(
        urllib.parse.parse_qsl(urllib.parse.urlparse(response.headers["location"]).fragment)
    )


# ---- the real provider ------------------------------------------------------------------------


def test_the_real_discovery_document_and_signing_keys_are_usable():
    doc = oidc_service.discovery(httpx.Client(timeout=30))
    assert doc["issuer"] == ISSUER and doc["authorization_endpoint"].startswith(KC)
    jwks = httpx.get(doc["jwks_uri"], timeout=30).json()["keys"]
    assert any(k.get("use") == "sig" and k.get("alg") == "RS256" for k in jwks)


def test_a_verified_user_signs_in_gets_a_personal_org_and_a_working_session(client):
    callback, _ = sso_round_trip(client, "alice", USERS["alice"][0])
    tokens = fragment(callback)
    assert tokens.keys() == {"access_token", "refresh_token"}
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=auth).json()["email"] == "alice@corp.example"
    orgs = client.get(f"{API}/orgs", headers=auth).json()
    assert len(orgs) == 1 and orgs[0]["role"] == "admin"
    assert (
        client.post(
            f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 200
    )
    rows = client.get(f"{API}/orgs/{orgs[0]['id']}/audit", headers=auth).json()
    assert "auth.sso_login" in {r["action"] for r in rows}


def test_a_second_login_by_the_same_person_reuses_the_account(client):
    first = fragment(sso_round_trip(client, "alice", USERS["alice"][0])[0])
    second = fragment(sso_round_trip(client, "alice", USERS["alice"][0])[0])
    ids = {
        client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {t['access_token']}"}
        ).json()["id"]
        for t in (first, second)
    }
    assert len(ids) == 1
    with client.factory() as db:
        assert db.query(User).count() == 1
        user = db.query(User).one()
        assert user.oidc_issuer == ISSUER and user.oidc_sub and user.password_hash is None


def test_a_wrong_password_never_reaches_loopforge(client):
    callback, login = sso_round_trip(client, "alice", "not-the-password")
    assert (
        callback is None
        and login.status_code == 200
        and "Invalid username or password" in login.text
    )
    with client.factory() as db:
        assert db.query(User).count() == 0


def test_an_unverified_email_is_refused(client):
    callback, _ = sso_round_trip(client, "bob", USERS["bob"][0])
    error = urllib.parse.unquote(urllib.parse.urlparse(callback.headers["location"]).fragment)
    assert error.startswith("error=") and "verified email" in error
    with client.factory() as db:
        assert db.query(User).count() == 0


def test_a_disallowed_email_domain_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "oidc_allowed_domains", "corp.example")
    callback, _ = sso_round_trip(client, "carol", USERS["carol"][0])
    assert "domain is not allowed" in urllib.parse.unquote(
        urllib.parse.urlparse(callback.headers["location"]).fragment
    )
    ok, _ = sso_round_trip(client, "alice", USERS["alice"][0])  # the allowed domain still works
    assert "access_token" in fragment(ok)


def test_a_wrong_client_secret_is_rejected_by_keycloak(client, monkeypatch):
    start = client.get(f"{API}/auth/sso/login", follow_redirects=False)
    cookie = start.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    login = keycloak_login(start.headers["location"], "alice", USERS["alice"][0])
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(login.headers["location"]).query))
    monkeypatch.setattr(settings, "oidc_client_secret", "definitely-wrong")
    client.cookies.clear()
    cb = client.get(
        f"{API}/auth/sso/callback",
        params={"code": query["code"], "state": query["state"]},
        headers={"cookie": f"lf_sso={cookie}"},
        follow_redirects=False,
    )
    assert "rejected" in urllib.parse.unquote(
        urllib.parse.urlparse(cb.headers["location"]).fragment
    )


def test_a_code_cannot_be_used_twice_against_the_real_provider(client):
    start = client.get(f"{API}/auth/sso/login", follow_redirects=False)
    cookie = start.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    login = keycloak_login(start.headers["location"], "alice", USERS["alice"][0])
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(login.headers["location"]).query))
    params = {"code": query["code"], "state": query["state"]}
    headers = {"cookie": f"lf_sso={cookie}"}
    client.cookies.clear()
    first = client.get(
        f"{API}/auth/sso/callback", params=params, headers=headers, follow_redirects=False
    )
    assert "access_token" in fragment(first)
    replay = client.get(
        f"{API}/auth/sso/callback", params=params, headers=headers, follow_redirects=False
    )
    assert "rejected" in urllib.parse.unquote(
        urllib.parse.urlparse(replay.headers["location"]).fragment
    )
