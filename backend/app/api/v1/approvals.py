"""Human approval gate (spec 13.2). The loop pauses itself; only the task's owner can release it."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    Principal,
    get_approver,
    get_developer,
    get_llm,
    get_sandbox,
    get_viewer,
)
from app.database.models import ApprovalComment, ApprovalRequest, AuditEvent, User
from app.database.session import get_db, get_session_factory
from app.execution.sandbox import Sandbox
from app.services import audit_service, run_service, task_service
from app.services.llm_client import LLMClient
from app.services.task_service import TaskStatus

router = APIRouter(prefix="/tasks", tags=["approvals"])


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    iteration_number: int
    status: str
    summary: str
    detail: dict[str, object]
    created_at: datetime
    decided_at: datetime | None


def _owned(db: Session, principal: Principal, task_id: uuid.UUID) -> None:
    if task_service.get_owned_task(db, principal.org_id, task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")


@router.get("/{task_id}/approvals", response_model=list[ApprovalOut])
def list_approvals(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[ApprovalRequest]:
    _owned(db, principal, task_id)
    return list(
        db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.task_id == task_id)
            .order_by(ApprovalRequest.created_at, ApprovalRequest.id)
        )
    )


def _pending(
    db: Session, principal: Principal, task_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalRequest:
    task = task_service.get_owned_task_for_update(db, principal.org_id, task_id)
    req = db.get(ApprovalRequest, approval_id)
    if task is None or req is None or req.task_id != task.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    if req.status != "pending" or task.status != TaskStatus.AWAITING_APPROVAL.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing is waiting for a decision")
    return req


def _decide(
    db: Session, req: ApprovalRequest, decision: str, principal: Principal, request: Request
) -> None:
    req.status = decision
    req.decided_at = datetime.now(UTC).replace(tzinfo=None)
    req.decided_by = principal.user.id
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action=f"approval.{decision}",
        target_type="task", target_id=req.task_id,
        detail={"approval": str(req.id), "kind": req.kind}, request=request, commit=False,
    )  # fmt: skip
    db.add(
        AuditEvent(
            task_id=req.task_id,
            event_type="approval_decided",
            event_data={"id": str(req.id), "kind": req.kind, "decision": decision},
        )
    )
    db.commit()


@router.post("/{task_id}/approvals/{approval_id}/approve", response_model=ApprovalOut)
def approve(
    request: Request,
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    background: BackgroundTasks,
    principal: Principal = Depends(get_approver),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ApprovalRequest:
    req = _pending(db, principal, task_id, approval_id)
    task = task_service.get_owned_task(db, principal.org_id, task_id)
    assert task is not None
    _decide(db, req, "approved", principal, request)
    task_service.transition(db, task, TaskStatus(req.resume_status))
    run_service.dispatch(background, factory, "resume", task.id, llm, sandbox)
    return req


@router.post("/{task_id}/approvals/{approval_id}/reject", response_model=ApprovalOut)
def reject(
    request: Request,
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    principal: Principal = Depends(get_approver),
    db: Session = Depends(get_db),
) -> ApprovalRequest:
    """Rejection escalates the task: a human said no, so it is never silently continued."""
    req = _pending(db, principal, task_id, approval_id)
    task = task_service.get_owned_task(db, principal.org_id, task_id)
    assert task is not None
    _decide(db, req, "rejected", principal, request)
    task_service.transition(db, task, TaskStatus.ESCALATED)
    return req


# ---- inline review comments (Phase 15) -------------------------------------------------------


class CommentIn(BaseModel):
    file_path: str = Field(default="", max_length=300)
    line: int | None = Field(default=None, ge=1)
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    author: str
    file_path: str
    line: int | None
    body: str
    created_at: datetime


def _approval_of(
    db: Session, principal: Principal, task_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalRequest:
    _owned(db, principal, task_id)
    req = db.get(ApprovalRequest, approval_id)
    if req is None or req.task_id != task_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    return req


def _comment_out(db: Session, c: ApprovalComment) -> CommentOut:
    author = db.get(User, c.user_id)
    return CommentOut(
        id=c.id, user_id=c.user_id, author=author.email if author else "", file_path=c.file_path,
        line=c.line, body=c.body, created_at=c.created_at,
    )  # fmt: skip


@router.get("/{task_id}/approvals/{approval_id}/comments", response_model=list[CommentOut])
def list_comments(
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[CommentOut]:
    _approval_of(db, principal, task_id, approval_id)
    rows = db.scalars(
        select(ApprovalComment)
        .where(ApprovalComment.approval_id == approval_id)
        .order_by(ApprovalComment.created_at, ApprovalComment.id)
    )
    return [_comment_out(db, c) for c in rows]


@router.post(
    "/{task_id}/approvals/{approval_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    data: CommentIn,
    request: Request,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> CommentOut:
    _approval_of(db, principal, task_id, approval_id)
    c = ApprovalComment(
        approval_id=approval_id, user_id=principal.user.id, file_path=data.file_path,
        line=data.line, body=data.body,
    )  # fmt: skip
    db.add(c)
    db.commit()
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="approval.comment",
        target_type="task", target_id=task_id, detail={"approval": str(approval_id)},
        request=request,
    )  # fmt: skip
    return _comment_out(db, c)
