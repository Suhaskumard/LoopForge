"""TOTP second factor: enrol, activate, status, disable (Phase 17, ADR-0024)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database.models import Membership, Organization, User
from app.database.session import get_db
from app.services import audit_service, mfa_service, org_service

router = APIRouter(prefix="/auth/mfa", tags=["auth"])


class MfaStatus(BaseModel):
    enabled: bool
    recovery_codes_left: int


class MfaEnrol(BaseModel):
    secret: str  # base32; shown once (enter it in an authenticator app, or use the URI/QR)
    otpauth_uri: str


class MfaCode(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaActivated(BaseModel):
    recovery_codes: list[str]  # shown exactly once


def _audit(db: Session, request: Request, user: User, action: str) -> None:
    ctx = org_service.resolve(db, user.id, None)
    audit_service.record(
        db, org_id=ctx.org_id if ctx else None, actor_id=user.id, action=action,
        target_type="user", target_id=user.id, request=request,
    )  # fmt: skip


@router.get("", response_model=MfaStatus)
def mfa_status(user: User = Depends(get_current_user)) -> MfaStatus:
    return MfaStatus(
        enabled=mfa_service.enabled(user), recovery_codes_left=len(user.recovery_codes or [])
    )


@router.post("/enroll", response_model=MfaEnrol)
def enroll(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MfaEnrol:
    try:
        secret = mfa_service.start_enrolment(db, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return MfaEnrol(secret=secret, otpauth_uri=mfa_service.provisioning_uri(secret, user.email))


@router.post("/activate", response_model=MfaActivated)
def activate(
    data: MfaCode,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MfaActivated:
    try:
        codes = mfa_service.activate(db, user, data.code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    _audit(db, request, user, "auth.mfa_enabled")
    return MfaActivated(recovery_codes=codes)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable(
    data: MfaCode,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not mfa_service.enabled(user):
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA is not enabled")
    mandatory = db.scalars(
        select(Organization.name)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user.id, Organization.require_mfa.is_(True))
    ).first()
    if mandatory is not None and user.password_hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{mandatory} requires MFA; leave it before disabling"
        )
    if mfa_service.verify_second_factor(db, user, data.code) is None:
        _audit(db, request, user, "auth.mfa_failed")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that code is not valid")
    mfa_service.disable(db, user)
    _audit(db, request, user, "auth.mfa_disabled")
