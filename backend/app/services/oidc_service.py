"""Generic OpenID Connect login (Phase 10, ADR-0017): authorization code + PKCE.

All provider traffic goes through an injectable `httpx.Client`, so tests use a fake provider
(`httpx.MockTransport`) with a locally generated RSA key and no network.

What is verified on the ID token: signature (key chosen by `kid` from the provider's JWKS),
`iss`, `aud`, `exp`, `iat`, `sub`, the `nonce` we generated, and `email_verified`. The `state`
and PKCE verifier travel in a short-lived signed cookie, so nothing is stored server-side.

Account linking is deliberately conservative: an existing *password* account with the same email
is NOT linked automatically, because LoopForge does not verify registration emails and
auto-linking would let someone who pre-registered a victim's address take over their SSO login.
"""

import base64
import hashlib
import secrets
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import User
from app.services import org_service

STATE_COOKIE = "lf_sso"
STATE_TTL_SECONDS = 600
ALLOWED_ALGS = ["RS256", "RS384", "RS512", "ES256", "ES384"]


class SSOError(Exception):
    """Login could not be completed; the message is safe to show to the user."""


def enabled() -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id)


def _http() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False)


_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def discovery(http: httpx.Client) -> dict[str, Any]:
    issuer = settings.oidc_issuer.rstrip("/")
    cached = _discovery_cache.get(issuer)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    resp = http.get(f"{issuer}/.well-known/openid-configuration")
    if resp.status_code != 200:
        raise SSOError("identity provider is unavailable")
    doc: dict[str, Any] = resp.json()
    if str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise SSOError("identity provider issuer mismatch")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(key):
            raise SSOError("identity provider metadata is incomplete")
    _discovery_cache[issuer] = (time.time(), doc)
    return doc


def clear_cache() -> None:
    _discovery_cache.clear()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass(frozen=True)
class LoginStart:
    url: str
    cookie: str


def _sign(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def start_login(http: httpx.Client | None = None) -> LoginStart:
    if not enabled():
        raise SSOError("SSO is not configured")
    meta = discovery(http or _http())
    state, nonce, verifier = (
        secrets.token_urlsafe(24),
        secrets.token_urlsafe(24),
        secrets.token_urlsafe(48),
    )
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_uri,
            "scope": settings.oidc_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    cookie = _sign(
        {"s": state, "n": nonce, "v": verifier, "exp": int(time.time()) + STATE_TTL_SECONDS}
    )
    return LoginStart(f"{meta['authorization_endpoint']}?{query}", cookie)


def _read_cookie(cookie: str | None) -> dict[str, str]:
    try:
        data = jwt.decode(cookie or "", settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise SSOError("login session expired; start again") from None
    return {k: str(data[k]) for k in ("s", "n", "v")}


def _verify_id_token(
    token: str, nonce: str, http: httpx.Client, meta: dict[str, Any]
) -> dict[str, Any]:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        keys = http.get(meta["jwks_uri"]).json().get("keys", [])
        jwk = next((k for k in keys if k.get("kid") == kid), None)
        if jwk is None:
            raise SSOError("signing key not found")
        claims: dict[str, Any] = jwt.decode(
            token,
            jwt.PyJWK.from_dict(jwk).key,
            algorithms=ALLOWED_ALGS,
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer.rstrip("/"),
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except SSOError:
        raise
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise SSOError(f"invalid ID token ({type(exc).__name__})") from None
    if claims.get("nonce") != nonce:
        raise SSOError("invalid ID token (nonce)")
    return claims


def _domain_allowed(email: str) -> bool:
    allowed = [d.strip().lower() for d in settings.oidc_allowed_domains.split(",") if d.strip()]
    return not allowed or email.rsplit("@", 1)[-1].lower() in allowed


def complete_login(
    db: Session,
    *,
    code: str,
    state: str,
    cookie: str | None,
    http: httpx.Client | None = None,
) -> User:
    if not enabled():
        raise SSOError("SSO is not configured")
    saved = _read_cookie(cookie)
    if not secrets.compare_digest(saved["s"], state):
        raise SSOError("state mismatch")
    client = http or _http()
    meta = discovery(client)
    resp = client.post(
        meta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.oidc_redirect_uri,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
            "code_verifier": saved["v"],
        },
    )
    if resp.status_code != 200 or "id_token" not in resp.json():
        raise SSOError("the identity provider rejected the login")
    claims = _verify_id_token(resp.json()["id_token"], saved["n"], client, meta)

    email = str(claims.get("email", "")).lower()
    if not email or claims.get("email_verified") is not True:
        raise SSOError("the identity provider did not supply a verified email")
    if not _domain_allowed(email):
        raise SSOError("this email domain is not allowed")

    issuer, sub = settings.oidc_issuer.rstrip("/"), str(claims["sub"])
    user = db.scalars(select(User).where(User.oidc_issuer == issuer, User.oidc_sub == sub)).first()
    if user is not None:
        return user
    existing = db.scalars(select(User).where(User.email == email)).first()
    if existing is not None:
        # Phase 15: link only when the LoopForge account's address was itself verified (a mailed
        # link was followed), so pre-registering someone else's address cannot capture their SSO.
        if existing.email_verified_at is not None and existing.oidc_sub is None:
            existing.oidc_issuer, existing.oidc_sub = issuer, sub
            db.commit()
            return existing
        raise SSOError(
            "an account with this email already exists; sign in with your password instead"
        )
    user = User(
        email=email, password_hash=None, oidc_issuer=issuer, oidc_sub=sub,
        email_verified_at=datetime.now(UTC).replace(tzinfo=None),  # the IdP verified it
    )  # fmt: skip
    user.id = uuid.uuid4()
    db.add(user)
    db.commit()
    org_service.create_personal_org(db, user)
    return user
