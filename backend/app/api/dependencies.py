import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database.models import User
from app.database.session import get_db
from app.execution.sandbox import Sandbox, get_sandbox_backend
from app.services import api_token_service, mfa_service, org_service
from app.services.llm_client import LLMClient, LLMError, get_llm_client
from app.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if api_token_service.is_api_token(token):  # Phase 11: scoped automation token
        row = api_token_service.authenticate(db, token)
        owner = db.get(User, row.user_id) if row is not None else None
        if row is None or owner is None or not owner.active:
            raise unauthorized
        request.state.api_token = row
        return owner
    claims = decode_access_token(token)
    if claims is None:
        raise unauthorized
    try:
        user = db.get(User, uuid.UUID(str(claims["sub"])))
    except ValueError:
        raise unauthorized from None
    if user is None or not user.active or claims.get("tv") != user.token_version:
        raise unauthorized
    return user


def _enforce_mfa(db: Session, user: User, org_id: uuid.UUID, request: Request) -> None:
    """An org can require a second factor. Passwordless (SSO-only) accounts are exempt: their
    identity provider owns authentication. API tokens are non-interactive and also exempt."""
    if (
        getattr(request.state, "api_token", None) is None
        and user.password_hash
        and user.totp_enabled_at is None
        and mfa_service.org_requires_mfa(db, org_id)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This organization requires MFA; enable it under account security",
            headers={"X-MFA-Enrolment-Required": "true"},
        )


def _capped(role: str, request: Request) -> str:
    """An API token can never exceed its scope, whatever the owner's membership role is."""
    tok = getattr(request.state, "api_token", None)
    if tok is None:
        return role
    capped: str = min(role, tok.scope, key=lambda r: org_service.ROLE_RANK[r])
    return capped


@dataclass(frozen=True)
class Principal:
    """Who is calling and in which organization (Phase 10). `org_id` scopes every query."""

    user: User
    org_id: uuid.UUID
    role: str


def get_principal(
    request: Request,
    user: User = Depends(get_current_user),
    x_org_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    requested: uuid.UUID | None = None
    if x_org_id:
        try:
            requested = uuid.UUID(x_org_id)
        except ValueError:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Not a member of that organization"
            ) from None
    tok = getattr(request.state, "api_token", None)
    if tok is not None:  # a token is bound to one organization
        if requested is not None and requested != tok.org_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Token is not valid for that organization"
            )
        requested = tok.org_id
    ctx = org_service.resolve(db, user.id, requested)
    if ctx is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of that organization")
    _enforce_mfa(db, user, ctx.org_id, request)
    return Principal(user, ctx.org_id, _capped(ctx.role, request))


def require_role(minimum: str) -> Callable[[Principal], Principal]:
    """Dependency factory: the caller's role in the active organization must be >= `minimum`."""

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if org_service.ROLE_RANK[principal.role] < org_service.ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires the {minimum} role")
        return principal

    return dependency


def require_org_role(minimum: str) -> Callable[..., Principal]:
    """Like `require_role`, for routes that carry the organization in the path (`/orgs/{org_id}`).

    A non-member gets 404, never 403, so the existence of other tenants is not disclosed.
    """

    def dependency(
        request: Request,
        org_id: uuid.UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Principal:
        tok = getattr(request.state, "api_token", None)
        ctx = (
            None
            if tok is not None and tok.org_id != org_id
            else org_service.resolve(db, user.id, org_id)
        )
        if ctx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
        _enforce_mfa(db, user, ctx.org_id, request)
        role = _capped(ctx.role, request)
        if org_service.ROLE_RANK[role] < org_service.ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires the {minimum} role")
        return Principal(user, ctx.org_id, role)

    return dependency


get_viewer = require_role("viewer")
get_developer = require_role("developer")
get_approver = require_role("approver")
get_admin = require_role("admin")


def get_llm() -> LLMClient:
    """LLM dependency; a missing/invalid provider configuration is a 503, not a crash."""
    try:
        return get_llm_client()
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None


def get_sandbox() -> Sandbox:
    return get_sandbox_backend()
