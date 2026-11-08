"""SCIM 2.0 endpoint + the admin routes that mint its tokens (Phase 17, ADR-0024)."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, require_org_role
from app.database.session import get_db
from app.services import audit_service, scim_service
from app.services.scim_service import ScimError

CONTENT_TYPE = "application/scim+json"


class ScimResponse(JSONResponse):
    media_type = CONTENT_TYPE


def _org_of_token(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> uuid.UUID:
    """The org a SCIM bearer token is bound to. Anything else (user JWT, API token) is refused."""
    scheme, _, bearer = (authorization or "").partition(" ")
    row = scim_service.authenticate(db, bearer.strip()) if scheme.lower() == "bearer" else None
    if row is None:
        raise ScimError(401, "Invalid or missing SCIM token")
    return row.org_id


router = APIRouter(prefix="/scim/v2", tags=["scim"], default_response_class=ScimResponse)


@router.get("/ServiceProviderConfig")
def service_provider_config(_: uuid.UUID = Depends(_org_of_token)) -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False},
        "filter": {"supported": True, "maxResults": scim_service.MAX_PAGE},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {"type": "oauthbearertoken", "name": "Bearer token", "primary": True}
        ],
    }


@router.get("/Users")
def list_users(
    filter: str | None = None,
    startIndex: int = 1,
    count: int = 100,
    org: uuid.UUID = Depends(_org_of_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return scim_service.list_users(db, org, filter, startIndex, count)


@router.post("/Users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: dict[str, Any], org: uuid.UUID = Depends(_org_of_token), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return scim_service.create_user(db, org, body)


@router.get("/Users/{user_id}")
def get_user(
    user_id: str, org: uuid.UUID = Depends(_org_of_token), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return scim_service.get_user(db, org, user_id)


@router.patch("/Users/{user_id}")
def patch_user(
    user_id: str,
    body: dict[str, Any],
    org: uuid.UUID = Depends(_org_of_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return scim_service.patch_user(db, org, user_id, body)


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str, org: uuid.UUID = Depends(_org_of_token), db: Session = Depends(get_db)
) -> Response:
    scim_service.delete_user(db, org, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/Groups")
def list_groups(
    org: uuid.UUID = Depends(_org_of_token), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return scim_service.list_groups(db, org)


@router.get("/Groups/{group_id}")
def get_group(
    group_id: str, org: uuid.UUID = Depends(_org_of_token), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return scim_service.get_group(db, org, group_id)


@router.patch("/Groups/{group_id}")
def patch_group(
    group_id: str,
    body: dict[str, Any],
    org: uuid.UUID = Depends(_org_of_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return scim_service.patch_group(db, org, group_id, body)


# ---- admin: manage the SCIM bearer tokens -----------------------------------------------------

admin_router = APIRouter(prefix="/orgs/{org_id}/scim-tokens", tags=["scim"])
admin = require_org_role("admin")


class ScimTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ScimTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ScimTokenCreated(ScimTokenOut):
    token: str  # shown exactly once


@admin_router.get("", response_model=list[ScimTokenOut])
def list_tokens(p: Principal = Depends(admin), db: Session = Depends(get_db)) -> list[Any]:
    return scim_service.list_tokens(db, p.org_id)


@admin_router.post("", response_model=ScimTokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(
    data: ScimTokenCreate,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> ScimTokenCreated:
    row, secret = scim_service.create_token(db, p.org_id, p.user.id, data.name)
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="scim.token_created",
        target_type="scim_token", target_id=row.id, request=request,
    )  # fmt: skip
    return ScimTokenCreated(**ScimTokenOut.model_validate(row).model_dump(), token=secret)


@admin_router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> Response:
    if scim_service.revoke_token(db, p.org_id, token_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="scim.token_revoked",
        target_type="scim_token", target_id=token_id, request=request,
    )  # fmt: skip
    return Response(status_code=status.HTTP_204_NO_CONTENT)
