import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.etag import check_if_match, set_etag
from app.database.models import AuditEvent, Task, User
from app.database.session import get_db
from app.schemas.task import AuditEventOut, TaskCreate, TaskOut
from app.services import project_service, task_service
from app.services.task_service import InvalidTransition, TaskStatus

router = APIRouter(prefix="/tasks", tags=["tasks"])


class StatusChange(BaseModel):
    status: TaskStatus


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create(
    data: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    project = project_service.get_project(db, user.id, data.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return task_service.create_task(
        db, project, data.requirement, data.max_iterations, data.acceptance_criteria
    )


@router.get("", response_model=list[TaskOut])
def list_all(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Task]:
    return task_service.list_owned_tasks(db, user.id, limit, offset)


@router.get("/{task_id}", response_model=TaskOut)
def get_one(
    task_id: uuid.UUID,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    task = task_service.get_owned_task(db, user.id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    set_etag(response, task.version)
    return task


@router.post("/{task_id}/status", response_model=TaskOut)
def change_status(
    task_id: uuid.UUID,
    body: StatusChange,
    response: Response,
    if_match: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    """Phase 1 stand-in so transition rules are exercisable; the orchestrator owns this later."""
    task = task_service.get_owned_task_for_update(db, user.id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    check_if_match(if_match, task.version)
    try:
        updated = task_service.transition(db, task, body.status)
    except InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    set_etag(response, updated.version)
    return updated


@router.get("/{task_id}/events", response_model=list[AuditEventOut])
def events(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[AuditEvent]:
    task = task_service.get_owned_task(db, user.id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task_service.list_task_events(db, task)
