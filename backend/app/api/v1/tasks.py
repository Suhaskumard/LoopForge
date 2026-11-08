import uuid

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_developer, get_viewer
from app.api.etag import check_if_match, set_etag
from app.config import settings
from app.database.models import AuditEvent, Task
from app.database.session import get_db
from app.schemas.task import AuditEventOut, TaskCreate, TaskOut
from app.services import (
    audit_service,
    project_service,
    quota_service,
    repo_import,
    source_service,
    task_service,
)
from app.services.task_service import InvalidTransition, TaskStatus

router = APIRouter(prefix="/tasks", tags=["tasks"])


class StatusChange(BaseModel):
    status: TaskStatus


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create(
    data: TaskCreate,
    request: Request,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Task:
    project = project_service.get_project(db, principal.org_id, data.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    try:
        quota_service.check_can_create_task(db, principal.org_id)
    except quota_service.QuotaExceeded as exc:
        audit_service.record(
            db, org_id=principal.org_id, actor_id=principal.user.id, action="quota.blocked",
            target_type="project", target_id=project.id, detail={"reason": str(exc)},
            request=request,
        )  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from None
    if data.token_budget is not None and data.token_budget > settings.max_token_budget:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"token_budget may not exceed the server limit ({settings.max_token_budget})",
        )
    if data.source_type == "git":
        try:
            repo_import.validate_git_url_syntax(data.git_url or "")
        except repo_import.RepoImportError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    task = task_service.create_task(
        db,
        project,
        data.requirement,
        data.max_iterations,
        data.acceptance_criteria,
        token_budget=data.token_budget,
        max_cost=data.max_cost,
        require_plan_approval=data.require_plan_approval,
        source_type=data.source_type,
        source_ref=data.git_url,
    )
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="task.create",
        target_type="task", target_id=task.id, detail={"project": str(project.id)}, request=request,
    )  # fmt: skip
    return task


@router.get("", response_model=list[TaskOut])
def list_all(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[Task]:
    return task_service.list_owned_tasks(db, principal.org_id, limit, offset)


@router.get("/{task_id}", response_model=TaskOut)
def get_one(
    task_id: uuid.UUID,
    response: Response,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> Task:
    task = task_service.get_owned_task(db, principal.org_id, task_id)
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
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Task:
    """Phase 1 stand-in so transition rules are exercisable; the orchestrator owns this later."""
    task = task_service.get_owned_task_for_update(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    check_if_match(if_match, task.version)
    try:
        updated = task_service.transition(db, task, body.status)
    except InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    set_etag(response, updated.version)
    return updated


@router.post("/{task_id}/source", response_model=TaskOut)
def upload_source(
    task_id: uuid.UUID,
    file: UploadFile,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Task:
    """Upload the starting repository as a zip (only for source_type=zip tasks, before start)."""
    task = task_service.get_owned_task(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.source_type != "zip":
        raise HTTPException(status.HTTP_409_CONFLICT, "task was not created with source_type 'zip'")
    if task.status != TaskStatus.PENDING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "the source can only change before start")
    blob = file.file.read(settings.repo_max_archive_bytes + 1)  # never read past the limit
    try:
        result = repo_import.import_zip(blob)
        source_service.seed_task(db, task, result, file.filename or "upload.zip")
    except repo_import.RepoImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return task


@router.get("/{task_id}/events", response_model=list[AuditEventOut])
def events(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[AuditEvent]:
    task = task_service.get_owned_task(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task_service.list_task_events(db, task)
