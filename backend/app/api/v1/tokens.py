"""Scoped API tokens (Phase 11, ADR-0018). Admin-only; tokens are capped below admin."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, require_org_role
from app.database.models import ApiToken
from app.database.session import get_db
from app.schemas.integrations import TokenCreate, TokenCreated, TokenOut
from app.services import api_token_service, audit_service

router = APIRouter(prefix="/orgs/{org_id}/tokens", tags=["api-tokens"])
admin = require_org_role("admin")


@router.get("", response_model=list[TokenOut])
def list_tokens(p: Principal = Depends(admin), db: Session = Depends(get_db)) -> list[ApiToken]:
    return api_token_service.list_tokens(db, p.org_id)


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(
    data: TokenCreate,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> TokenCreated:
    row, secret = api_token_service.create(
        db,
        org_id=p.org_id,
        user_id=p.user.id,
        name=data.name,
        scope=data.scope,
        expires_days=data.expires_days,
    )
    audit_service.record(
        db,
        org_id=p.org_id,
        actor_id=p.user.id,
        action="token.create",
        target_type="api_token",
        target_id=row.id,
        detail={"name": row.name, "scope": row.scope},
        request=request,
    )
    return TokenCreated(**TokenOut.model_validate(row).model_dump(), token=secret)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> Response:
    if api_token_service.revoke(db, p.org_id, token_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    audit_service.record(
        db,
        org_id=p.org_id,
        actor_id=p.user.id,
        action="token.revoke",
        target_type="api_token",
        target_id=token_id,
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
