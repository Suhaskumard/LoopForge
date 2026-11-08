"""Human approval gate (spec 13.2). The loop pauses itself; only the task's owner can release it."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_user, get_llm, get_sandbox
from app.database.models import ApprovalRequest, AuditEvent, User
from app.database.session import get_db, get_session_factory
from app.execution.sandbox import Sandbox
from app.services import run_service, task_service
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


def _owned(db: Session, user: User, task_id: uuid.UUID) -> None:
    if task_service.get_owned_task(db, user.id, task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")


@router.get("/{task_id}/approvals", response_model=list[ApprovalOut])
def list_approvals(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ApprovalRequest]:
    _owned(db, user, task_id)
    return list(
        db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.task_id == task_id)
            .order_by(ApprovalRequest.created_at, ApprovalRequest.id)
        )
    )


def _pending(
    db: Session, user: User, task_id: uuid.UUID, approval_id: uuid.UUID
) -> ApprovalRequest:
    task = task_service.get_owned_task_for_update(db, user.id, task_id)
    req = db.get(ApprovalRequest, approval_id)
    if task is None or req is None or req.task_id != task.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    if req.status != "pending" or task.status != TaskStatus.AWAITING_APPROVAL.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing is waiting for a decision")
    return req


def _decide(db: Session, req: ApprovalRequest, decision: str) -> None:
    req.status = decision
    req.decided_at = datetime.now(UTC).replace(tzinfo=None)
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
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ApprovalRequest:
    req = _pending(db, user, task_id, approval_id)
    task = task_service.get_owned_task(db, user.id, task_id)
    assert task is not None
    _decide(db, req, "approved")
    task_service.transition(db, task, TaskStatus(req.resume_status))
    background.add_task(run_service.resume_run, factory, task.id, llm, sandbox)
    return req


@router.post("/{task_id}/approvals/{approval_id}/reject", response_model=ApprovalOut)
def reject(
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovalRequest:
    """Rejection escalates the task: a human said no, so it is never silently continued."""
    req = _pending(db, user, task_id, approval_id)
    task = task_service.get_owned_task(db, user.id, task_id)
    assert task is not None
    _decide(db, req, "rejected")
    task_service.transition(db, task, TaskStatus.ESCALATED)
    return req
