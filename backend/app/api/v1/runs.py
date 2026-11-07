"""Start a task and inspect what the agents produced (owner-scoped; foreign ids are 404)."""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_user, get_llm
from app.api.etag import check_if_match, set_etag
from app.database.models import AgentRun, Artifact, Iteration, Requirement, Task, User
from app.database.session import get_db, get_session_factory
from app.schemas.run import AgentRunOut, FileContentOut, FileOut, PlanOut, RequirementOut
from app.schemas.task import TaskOut
from app.services import run_service, task_service, workspace
from app.services.llm_client import LLMClient
from app.services.workspace import WorkspaceError

router = APIRouter(prefix="/tasks", tags=["runs"])


def _task(db: Session, user: User, task_id: uuid.UUID) -> Task:
    task = task_service.get_owned_task(db, user.id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


def _latest_iteration(db: Session, task: Task) -> Iteration | None:
    return db.scalars(
        select(Iteration)
        .where(Iteration.task_id == task.id)
        .order_by(Iteration.iteration_number.desc())
    ).first()


@router.post("/{task_id}/start", response_model=TaskOut, status_code=status.HTTP_202_ACCEPTED)
def start(
    task_id: uuid.UUID,
    background: BackgroundTasks,
    response: Response,
    if_match: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Task:
    task = task_service.get_owned_task_for_update(db, user.id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    check_if_match(if_match, task.version)
    try:
        task = run_service.prepare_start(db, task)
    except run_service.NotStartable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    background.add_task(run_service.execute_run, factory, task.id, llm)
    set_etag(response, task.version)
    return task


@router.get("/{task_id}/plan", response_model=PlanOut)
def get_plan(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PlanOut:
    task = _task(db, user, task_id)
    iteration = _latest_iteration(db, task)
    plan: dict[str, Any] | None = iteration.feedback.get("plan") if iteration else None
    if iteration is None or plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No plan yet")
    return PlanOut(iteration=iteration.iteration_number, plan=plan)


@router.get("/{task_id}/requirements", response_model=list[RequirementOut])
def requirements(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Requirement]:
    task = _task(db, user, task_id)
    return list(
        db.scalars(
            select(Requirement).where(Requirement.task_id == task.id).order_by(Requirement.req_id)
        )
    )


@router.get("/{task_id}/agent-runs", response_model=list[AgentRunOut])
def agent_runs(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[AgentRun]:
    task = _task(db, user, task_id)
    stmt = (
        select(AgentRun)
        .join(Iteration, AgentRun.iteration_id == Iteration.id)
        .where(Iteration.task_id == task.id)
        .order_by(Iteration.iteration_number, AgentRun.started_at, AgentRun.id)
    )
    return list(db.scalars(stmt))


def _source_artifacts(db: Session, iteration: Iteration) -> list[Artifact]:
    rows = db.scalars(
        select(Artifact).where(
            Artifact.iteration_id == iteration.id, Artifact.artifact_type == "source"
        )
    )
    # Sorted in Python, not SQL: database collations order '_' and '/' differently.
    return sorted(rows, key=lambda a: a.file_name)


@router.get("/{task_id}/files", response_model=list[FileOut])
def list_files(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FileOut]:
    task = _task(db, user, task_id)
    iteration = _latest_iteration(db, task)
    if iteration is None:
        return []
    return [
        FileOut(
            path=a.file_name,
            sha256=a.file_hash,
            iteration=iteration.iteration_number,
            created_at=a.created_at,
        )
        for a in _source_artifacts(db, iteration)
    ]


@router.get("/{task_id}/files/{file_path:path}", response_model=FileContentOut)
def read_file(
    task_id: uuid.UUID,
    file_path: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileContentOut:
    task = _task(db, user, task_id)
    iteration = _latest_iteration(db, task)
    known = {a.file_name: a for a in _source_artifacts(db, iteration)} if iteration else {}
    if iteration is None or file_path not in known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    try:
        content = workspace.read_file(
            workspace.iteration_dir(task.id, iteration.iteration_number), file_path
        )
    except WorkspaceError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    return FileContentOut(path=file_path, sha256=known[file_path].file_hash, content=content)
