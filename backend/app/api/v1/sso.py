"""SSO routes (Phase 10): `GET /auth/config`, `GET /auth/sso/login`, `GET /auth/sso/callback`."""

import urllib.parse

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.auth import _token_pair
from app.config import settings
from app.database.session import get_db
from app.services import audit_service, auth_service, oidc_service, org_service

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_PATH = "/api/v1/auth/sso"


class AuthConfig(BaseModel):
    sso_enabled: bool


@router.get("/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    return AuthConfig(sso_enabled=oidc_service.enabled())


def _fail(message: str) -> RedirectResponse:
    """Errors go back to the login page; the message is one of our own safe strings."""
    target = f"{settings.sso_frontend_url}#error={urllib.parse.quote(message)}"
    resp = RedirectResponse(target, status_code=302)
    resp.delete_cookie(oidc_service.STATE_COOKIE, path=COOKIE_PATH)
    return resp


@router.get("/sso/login")
def sso_login() -> RedirectResponse:
    try:
        start = oidc_service.start_login()
    except oidc_service.SSOError as exc:
        return _fail(str(exc))
    resp = RedirectResponse(start.url, status_code=302)
    resp.set_cookie(
        oidc_service.STATE_COOKIE,
        start.cookie,
        max_age=oidc_service.STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        path=COOKIE_PATH,
    )
    return resp


@router.get("/sso/callback")
def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    lf_sso: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error or not code or not state:
        return _fail("login was cancelled or failed")
    try:
        user = oidc_service.complete_login(db, code=code, state=state, cookie=lf_sso)
    except oidc_service.SSOError as exc:
        return _fail(str(exc))
    ctx = org_service.resolve(db, user.id, None)
    audit_service.record(
        db, org_id=ctx.org_id if ctx else None, actor_id=user.id, action="auth.sso_login",
        target_type="user", target_id=user.id, detail={"issuer": settings.oidc_issuer},
        request=request,
    )  # fmt: skip
    pair = _token_pair(user, auth_service.start_session(db, user))
    # Tokens travel in the URL *fragment*: it is never sent to a server or written to access logs.
    fragment = urllib.parse.urlencode(
        {"access_token": pair.access_token, "refresh_token": pair.refresh_token}
    )
    resp = RedirectResponse(f"{settings.sso_frontend_url}#{fragment}", status_code=302)
    resp.delete_cookie(oidc_service.STATE_COOKIE, path=COOKIE_PATH)
    return resp
