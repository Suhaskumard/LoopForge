"""Pull-request delivery behind a human approval (Phase 11, ADR-0018)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    get_approver,
    get_developer,
    get_viewer,
    require_org_role,
)
from app.api.pagination import Pager, pager
from app.database.models import PublishRequest
from app.database.session import get_db
from app.schemas.integrations import GithubStatusOut, GithubTokenIn, PublishCreate, PublishOut
from app.services import audit_service, publish_service, task_service
from app.services.publish_service import PublishError

router = APIRouter(tags=["publish"])
org_admin = require_org_role("admin")


def _fail(exc: PublishError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.post(
    "/tasks/{task_id}/publish", response_model=PublishOut, status_code=status.HTTP_201_CREATED
)
def request_publish(
    task_id: uuid.UUID,
    data: PublishCreate,
    request: Request,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> PublishRequest:
    task = task_service.get_owned_task(db, p.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    try:
        return publish_service.request_publish(
            db,
            task=task,
            org_id=p.org_id,
            user_id=p.user.id,
            repo=data.repo,
            base_branch=data.base_branch,
            request=request,
        )
    except PublishError as exc:
        raise _fail(exc) from None


@router.get("/tasks/{task_id}/publish", response_model=list[PublishOut])
def list_publish(
    task_id: uuid.UUID,
    p: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
    page: Pager = Depends(pager()),
) -> list[PublishRequest]:
    if task_service.get_owned_task(db, p.org_id, task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    rows = page.slice(list(publish_service.list_for_task(db, p.org_id, task_id)))
    return [publish_service.refresh_ci(db, r) for r in rows]


@router.post("/publish/{publish_id}/approve", response_model=PublishOut)
def approve(
    publish_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(get_approver),
    db: Session = Depends(get_db),
) -> PublishRequest:
    try:
        return publish_service.approve_and_push(
            db, org_id=p.org_id, user_id=p.user.id, publish_id=publish_id, request=request
        )
    except PublishError as exc:
        raise _fail(exc) from None


@router.post("/publish/{publish_id}/reject", response_model=PublishOut)
def reject(
    publish_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(get_approver),
    db: Session = Depends(get_db),
) -> PublishRequest:
    try:
        return publish_service.reject(
            db, org_id=p.org_id, user_id=p.user.id, publish_id=publish_id, request=request
        )
    except PublishError as exc:
        raise _fail(exc) from None


@router.put("/orgs/{org_id}/integrations/github", response_model=GithubStatusOut)
def set_github_token(
    data: GithubTokenIn,
    request: Request,
    p: Principal = Depends(org_admin),
    db: Session = Depends(get_db),
) -> GithubStatusOut:
    publish_service.save_token(db, p.org_id, data.token)
    audit_service.record(
        db,
        org_id=p.org_id,
        actor_id=p.user.id,
        action="integration.github_token_set",
        target_type="org",
        target_id=p.org_id,
        request=request,
    )
    return GithubStatusOut(configured=True)
