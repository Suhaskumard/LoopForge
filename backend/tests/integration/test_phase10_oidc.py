"""Phase 10 OIDC login against a fake identity provider (local RSA key, httpx.MockTransport)."""

import base64
import hashlib
import json
import time
import urllib.parse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings
from app.database.models import User
from app.services import oidc_service
from tests.conftest import register_and_login
from tests.integration.test_phase10_authz import _fast_bcrypt

API = "/api/v1"
ISSUER = "https://idp.example.com"
CLIENT_ID = "loopforge-client"
KID = "key-1"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = _key()
OTHER_KEY = _key()


def _jwks(key) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}


class Provider:
    """A tiny scriptable identity provider."""

    def __init__(self) -> None:
        self.claims: dict = {}
        self.sign_with = SIGNING_KEY
        self.algorithm = "RS256"
        self.codes: dict[str, dict] = {}
        self.token_status = 200
        self.token_requests: list[dict] = []
        self.nonce = ""
        self.challenge = ""

    def id_token(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "user-123",
            "email": "sso.user@corp.example",
            "email_verified": True,
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            **self.claims,
            **overrides,
        }
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.sign_with, algorithm=self.algorithm, headers={"kid": KID})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if url.endswith("/jwks"):
            return httpx.Response(200, json=_jwks(SIGNING_KEY))
        if url.endswith("/token"):
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            self.token_requests.append(form)
            code = form["code"]
            if self.token_status != 200 or code in self.codes:  # one-time codes
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.codes[code] = form
            return httpx.Response(200, json={"id_token": self.id_token(), "access_token": "x"})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch):
    provider = Provider()
    http = httpx.Client(transport=httpx.MockTransport(provider.handler))
    monkeypatch.setattr(oidc_service, "_http", lambda: http)
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "oidc_client_secret", "shh-client-secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://testserver/api/v1/auth/sso/callback")
    monkeypatch.setattr(settings, "oidc_allowed_domains", "")
    monkeypatch.setattr(settings, "sso_frontend_url", "http://app.example/login")
    oidc_service.clear_cache()
    _fast_bcrypt(monkeypatch)
    yield provider
    oidc_service.clear_cache()


def begin(client, idp):
    """Hit /sso/login; return (state, cookie) and tell the provider which nonce to echo."""
    client.cookies.clear()
    r = client.get(f"{API}/auth/sso/login", follow_redirects=False)
    assert r.status_code == 302
    set_cookie = r.headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie.replace("Lax", "lax")
    assert "Path=/api/v1/auth/sso" in set_cookie
    location = urllib.parse.urlparse(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
    q = dict(urllib.parse.parse_qsl(location.query))
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["client_id"] == CLIENT_ID and q["scope"] == "openid email profile"
    idp.nonce, idp.challenge = q["nonce"], q["code_challenge"]
    cookie = set_cookie.split(";", 1)[0].split("=", 1)[1]
    client.cookies.clear()  # the test sends the cookie explicitly, like a browser would
    return q["state"], cookie


def finish(client, state, cookie, code="code-1"):
    headers = {"cookie": f"lf_sso={cookie}"} if cookie is not None else {}
    return client.get(
        f"{API}/auth/sso/callback",
        params={"code": code, "state": state},
        headers=headers,
        follow_redirects=False,
    )


def fragment(response) -> dict:
    assert response.status_code == 302
    return dict(
        urllib.parse.parse_qsl(urllib.parse.urlparse(response.headers["location"]).fragment)
    )


def login(client, idp, code="code-1"):
    state, cookie = begin(client, idp)
    return finish(client, state, cookie, code)


def test_config_reports_sso_enabled(client, idp):
    assert client.get(f"{API}/auth/config").json() == {"sso_enabled": True}


def test_successful_login_creates_the_user_a_personal_org_and_a_session(client, idp):
    r = login(client, idp)
    tokens = fragment(r)
    assert tokens.keys() == {"access_token", "refresh_token"}  # in the fragment, never the query
    assert "?" not in r.headers["location"]
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=auth).json()["email"] == "sso.user@corp.example"
    orgs = client.get(f"{API}/orgs", headers=auth).json()
    assert len(orgs) == 1 and orgs[0]["role"] == "admin"
    # PKCE: the verifier sent to the token endpoint matches the challenge sent to /authorize
    sent = idp.token_requests[0]
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == idp.challenge
    assert (
        sent["client_secret"] == "shh-client-secret" and sent["grant_type"] == "authorization_code"
    )
    # the refresh token really works, and the state cookie was cleared
    assert (
        client.post(
            f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 200
    )
    cleared = r.headers["set-cookie"]
    assert cleared.startswith("lf_sso=") and "Max-Age=0" in cleared  # the state cookie is cleared
    audit_org = orgs[0]["id"]
    rows = client.get(f"{API}/orgs/{audit_org}/audit", headers=auth).json()
    assert "auth.sso_login" in {x["action"] for x in rows}


def test_a_second_login_reuses_the_same_user(client, idp, db_path):
    first = fragment(login(client, idp, "code-1"))
    second = fragment(login(client, idp, "code-2"))
    ids = {
        client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {t['access_token']}"}
        ).json()["id"]
        for t in (first, second)
    }
    assert len(ids) == 1
    with client.factory() as db:
        assert db.query(User).count() == 1


def test_an_sso_only_user_cannot_use_password_login(client, idp):
    login(client, idp)
    r = client.post(
        f"{API}/auth/login", data={"username": "sso.user@corp.example", "password": "password123"}
    )
    assert r.status_code == 401


def error_of(response) -> str:
    assert response.status_code == 302
    frag = urllib.parse.urlparse(response.headers["location"]).fragment
    assert frag.startswith("error="), frag
    return urllib.parse.unquote(frag[len("error=") :])


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("wrong_issuer", "invalid ID token"),
        ("wrong_audience", "invalid ID token"),
        ("expired", "invalid ID token"),
        ("wrong_nonce", "nonce"),
        ("bad_signature", "invalid ID token"),
        ("hs256_with_public_key", "invalid ID token"),
        ("unverified_email", "verified email"),
        ("no_email", "verified email"),
        ("missing_sub", "invalid ID token"),
        ("disallowed_domain", "domain is not allowed"),
    ],
)
def test_bad_id_tokens_are_rejected(client, idp, monkeypatch, scenario, message):
    state, cookie = begin(client, idp)
    if scenario == "wrong_issuer":
        idp.claims = {"iss": "https://evil.example.com"}
    elif scenario == "wrong_audience":
        idp.claims = {"aud": "someone-else"}
    elif scenario == "expired":
        idp.claims = {"iat": int(time.time()) - 900, "exp": int(time.time()) - 600}
    elif scenario == "wrong_nonce":
        idp.claims = {"nonce": "replayed-from-another-login"}
    elif scenario == "bad_signature":
        idp.sign_with = OTHER_KEY
    elif scenario == "hs256_with_public_key":  # algorithm-confusion attack
        idp.algorithm = "HS256"
        idp.sign_with = "not-a-real-secret-but-long-enough-for-hs256-use"
    elif scenario == "unverified_email":
        idp.claims = {"email_verified": False}
    elif scenario == "no_email":
        idp.claims = {"email": None}
    elif scenario == "missing_sub":
        idp.claims = {"sub": None}
    elif scenario == "disallowed_domain":
        monkeypatch.setattr(settings, "oidc_allowed_domains", "corp.example,partner.example")
        idp.claims = {"email": "someone@gmail.com"}
    assert message in error_of(finish(client, state, cookie))
    with client.factory() as db:
        assert db.query(User).count() == 0  # no account was created by a rejected login


def test_an_allowed_domain_is_accepted(client, idp, monkeypatch):
    monkeypatch.setattr(settings, "oidc_allowed_domains", "other.example, corp.example")
    assert "access_token" in fragment(login(client, idp))


def test_state_and_cookie_problems_are_rejected(client, idp):
    state, cookie = begin(client, idp)
    assert "state mismatch" in error_of(finish(client, "different-state", cookie))
    assert "expired" in error_of(finish(client, state, None))  # no cookie at all
    assert "expired" in error_of(finish(client, state, "garbage"))
    stale = jwt.encode(
        {"s": state, "n": idp.nonce, "v": "v", "exp": int(time.time()) - 5},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert "expired" in error_of(finish(client, state, stale))
    forged = jwt.encode(
        {"s": state, "n": idp.nonce, "v": "v", "exp": int(time.time()) + 500},
        "attacker-secret-attacker-secret-1234",
        algorithm=settings.jwt_algorithm,
    )
    assert "expired" in error_of(finish(client, state, forged))  # not signed by us


def test_a_code_can_only_be_used_once(client, idp):
    assert "access_token" in fragment(login(client, idp, "same-code"))
    state, cookie = begin(client, idp)
    assert "rejected" in error_of(finish(client, state, cookie, "same-code"))


def test_the_provider_rejecting_the_code_is_reported(client, idp):
    idp.token_status = 400
    state, cookie = begin(client, idp)
    assert "rejected" in error_of(finish(client, state, cookie))


def test_provider_error_or_missing_code_returns_to_the_login_page(client, idp):
    r = client.get(
        f"{API}/auth/sso/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert "cancelled" in error_of(r)
    r = client.get(f"{API}/auth/sso/callback", follow_redirects=False)
    assert "cancelled" in error_of(r)


def test_an_existing_password_account_is_not_taken_over(client, idp):
    register_and_login(client, "sso.user@corp.example")  # someone pre-registered this address
    assert "already exists" in error_of(login(client, idp))
    with client.factory() as db:
        user = db.query(User).one()
        assert user.oidc_sub is None and user.password_hash  # untouched


def test_unconfigured_sso_is_refused_and_hidden(client, monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "")
    assert client.get(f"{API}/auth/config").json() == {"sso_enabled": False}
    r = client.get(f"{API}/auth/sso/login", follow_redirects=False)
    assert "not configured" in error_of(r)


def test_discovery_must_match_the_configured_issuer(client, idp, monkeypatch):
    def evil(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "issuer": "https://other.example.com",
                "authorization_endpoint": "x",
                "token_endpoint": "x",
                "jwks_uri": "x",
            },
        )

    monkeypatch.setattr(
        oidc_service, "_http", lambda: httpx.Client(transport=httpx.MockTransport(evil))
    )
    oidc_service.clear_cache()
    assert "issuer mismatch" in error_of(
        client.get(f"{API}/auth/sso/login", follow_redirects=False)
    )


def test_configuration_is_validated():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="OIDC_CLIENT_ID"):
        Settings(oidc_issuer="https://idp.example.com", oidc_client_id="", oidc_client_secret="")
    with pytest.raises(ValidationError, match="https"):
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            llm_provider="openai",
            sandbox_backend="docker",
            oidc_issuer="http://idp.example.com",
            oidc_client_id="a",
            oidc_client_secret="b",
        )
    assert Settings(oidc_issuer="").oidc_issuer == ""  # off by default
