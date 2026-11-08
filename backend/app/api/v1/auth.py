import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config import settings
from app.database.models import User
from app.database.session import get_db
from app.schemas.user import (
    EmailBody,
    RefreshRequest,
    ResetConfirm,
    SessionOut,
    Token,
    TokenBody,
    UserCreate,
    UserOut,
)
from app.services import audit_service, auth_service, email_token_service, mail_service, org_service
from app.utils.client_ip import client_ip
from app.utils.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(user: User, refresh_token: str) -> Token:
    return Token(
        access_token=create_access_token(str(user.id), user.token_version),
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


def _audit_auth(db: Session, request: Request, email: str, action: str, *, reason: str) -> None:
    """Record a failed or blocked login for an EXISTING account.

    Unknown emails are deliberately not written: anyone could otherwise fill the audit log with
    random addresses. The email is stored as a short hash, not in clear text.
    """
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None:
        return
    ctx = org_service.resolve(db, user.id, None)
    audit_service.record(
        db, org_id=ctx.org_id if ctx else None, actor_id=user.id, action=action,
        target_type="user", target_id=user.id,
        detail={"reason": reason, "email_sha256": hashlib.sha256(email.encode()).hexdigest()[:16]},
        request=request,
    )  # fmt: skip


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    data: UserCreate,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> User:
    email = data.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    org = org_service.create_personal_org(db, user)
    audit_service.record(
        db, org_id=org.id, actor_id=user.id, action="auth.register", target_type="user",
        target_id=user.id, request=request,
    )  # fmt: skip
    background.add_task(
        mail_service.send_verification, user.email, email_token_service.issue(db, user, "verify")
    )
    return user


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    email = form.username.lower()
    key = f"{client_ip(request)}|{email}"
    if auth_service.is_login_blocked(db, key):
        _audit_auth(db, request, email, "auth.login_blocked", reason="too_many_failures")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts; try again later",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    user = db.scalars(select(User).where(User.email == email)).first()
    if (
        user is None
        or not user.password_hash
        or not verify_password(form.password, user.password_hash)
    ):
        auth_service.record_login_failure(db, key)  # SSO-only users have no password to match
        reason = (
            "unknown_user"
            if user is None
            else "sso_only"
            if not user.password_hash
            else "bad_password"
        )
        _audit_auth(db, request, email, "auth.login_failed", reason=reason)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    auth_service.clear_login_failures(db, key)
    ctx = org_service.resolve(db, user.id, None)
    audit_service.record(
        db, org_id=ctx.org_id if ctx else None, actor_id=user.id, action="auth.login",
        target_type="user", target_id=user.id, detail={"method": "password"}, request=request,
    )  # fmt: skip
    return _token_pair(
        user,
        auth_service.start_session(
            db, user, request.headers.get("user-agent", ""), client_ip(request)
        ),
    )


@router.post("/refresh", response_model=Token)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> Token:
    try:
        user, new_token = auth_service.rotate(db, body.refresh_token)
    except auth_service.RefreshTokenReuse as reuse:
        owner = db.get(User, reuse.user_id)
        if owner is not None:
            ctx = org_service.resolve(db, owner.id, None)
            audit_service.record(
                db, org_id=ctx.org_id if ctx else None, actor_id=owner.id,
                action="auth.refresh_reuse", target_type="user", target_id=owner.id,
                detail={"note": "spent refresh token replayed; session family revoked"},
                request=request,
            )  # fmt: skip
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None
    except auth_service.InvalidRefreshToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None
    return _token_pair(user, new_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: Session = Depends(get_db)) -> Response:
    auth_service.revoke(db, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    auth_service.revoke_all(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


# ---- Phase 15: email verification, password reset, sessions --------------------------------

_GENERIC = {"detail": "If that address is registered, an email is on its way."}


@router.post("/verify-email", response_model=UserOut)
def verify_email(body: TokenBody, db: Session = Depends(get_db)) -> User:
    user = email_token_service.consume(db, body.token, "verify")
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
    return user


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if user.email_verified_at is None:
        background.add_task(
            mail_service.send_verification,
            user.email,
            email_token_service.issue(db, user, "verify"),
        )
    return {"detail": "Verification email sent if the address is not yet verified."}


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def password_reset_request(
    body: EmailBody, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
) -> dict[str, str]:
    """Always answers 202 with the same body: it never reveals whether the address exists."""
    email = body.email.lower()
    key = f"reset|{client_ip(request)}|{email}"
    if auth_service.is_login_blocked(db, key):
        return _GENERIC
    auth_service.record_login_failure(db, key)  # counts every request, known address or not
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is not None:
        background.add_task(
            mail_service.send_reset, user.email, email_token_service.issue(db, user, "reset")
        )
        _audit_auth(db, request, email, "auth.password_reset_requested", reason="requested")
    return _GENERIC


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_confirm(
    body: ResetConfirm, request: Request, db: Session = Depends(get_db)
) -> Response:
    user = email_token_service.consume(db, body.token, "reset")
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired link")
    user.password_hash = hash_password(body.password)
    if user.email_verified_at is None:  # the link proves control of the inbox
        user.email_verified_at = datetime.now(UTC).replace(tzinfo=None)
    auth_service.revoke_all(db, user)  # every existing session ends
    ctx = org_service.resolve(db, user.id, None)
    audit_service.record(
        db, org_id=ctx.org_id if ctx else None, actor_id=user.id,
        action="auth.password_reset", target_type="user", target_id=user.id, request=request,
    )  # fmt: skip
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions", response_model=list[SessionOut])
def sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_refresh_token: str | None = Header(default=None),
) -> list[SessionOut]:
    current = auth_service.family_of(db, x_refresh_token) if x_refresh_token else None
    return [
        SessionOut(
            family_id=r.family_id, user_agent=r.user_agent, ip=r.ip, created_at=r.created_at,
            last_used_at=r.last_used_at, current=r.family_id == current,
        )
        for r in auth_service.list_sessions(db, user)
    ]  # fmt: skip


@router.delete("/sessions/{family_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    family_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    if not auth_service.revoke_session(db, user, family_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
