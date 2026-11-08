"""Start a task and inspect what the agents produced (owner-scoped; foreign ids are 404)."""

import io
import uuid
import zipfile
from typing import Any

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
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import Principal, get_developer, get_llm, get_sandbox, get_viewer
from app.api.etag import check_if_match, set_etag
from app.database.models import (
    AgentRun,
    Artifact,
    Iteration,
    Requirement,
    Task,
    TestResult,
)
from app.database.session import get_db, get_session_factory
from app.execution.sandbox import Sandbox
from app.schemas.run import (
    AgentRunOut,
    FileContentOut,
    FileDiffOut,
    FileOut,
    IterationDetailOut,
    IterationDiffOut,
    IterationOut,
    LogOut,
    PlanOut,
    RequirementOut,
    TestResultOut,
)
from app.schemas.task import TaskOut
from app.services import audit_service, quota_service, run_service, task_service, workspace
from app.services.llm_client import LLMClient
from app.services.workspace import WorkspaceError

router = APIRouter(prefix="/tasks", tags=["runs"])
iterations_router = APIRouter(prefix="/iterations", tags=["iterations"])


def _task(db: Session, principal: Principal, task_id: uuid.UUID) -> Task:
    task = task_service.get_owned_task(db, principal.org_id, task_id)
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
    request: Request,
    background: BackgroundTasks,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Task:
    task = task_service.get_owned_task_for_update(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    check_if_match(if_match, task.version)
    try:
        quota_service.check_can_start(db, principal.org_id)
    except quota_service.QuotaExceeded as exc:
        audit_service.record(
            db, org_id=principal.org_id, actor_id=principal.user.id, action="quota.blocked",
            target_type="task", target_id=task.id, detail={"reason": str(exc)}, request=request,
        )  # fmt: skip
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from None
    try:
        task = run_service.prepare_start(db, task)
    except run_service.NotStartable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="task.start",
        target_type="task", target_id=task.id, request=request,
    )  # fmt: skip
    run_service.dispatch(background, factory, "start", task.id, llm, sandbox)
    set_etag(response, task.version)
    return task


@router.get("/{task_id}/plan", response_model=PlanOut)
def get_plan(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> PlanOut:
    """The validated plan. Repair iterations carry no plan of their own, so this is the plan of
    the most recent iteration that has one (the plan the whole task is working to)."""
    task = _task(db, principal, task_id)
    iterations = db.scalars(
        select(Iteration)
        .where(Iteration.task_id == task.id)
        .order_by(Iteration.iteration_number.desc())
    )
    for iteration in iterations:
        plan: dict[str, Any] | None = iteration.feedback.get("plan")
        if plan is not None:
            return PlanOut(iteration=iteration.iteration_number, plan=plan)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "No plan yet")


@router.get("/{task_id}/requirements", response_model=list[RequirementOut])
def requirements(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[Requirement]:
    task = _task(db, principal, task_id)
    return list(
        db.scalars(
            select(Requirement).where(Requirement.task_id == task.id).order_by(Requirement.req_id)
        )
    )


@router.get("/{task_id}/agent-runs", response_model=list[AgentRunOut])
def agent_runs(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[AgentRun]:
    task = _task(db, principal, task_id)
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
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[FileOut]:
    task = _task(db, principal, task_id)
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
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> FileContentOut:
    task = _task(db, principal, task_id)
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


@router.get("/{task_id}/download")
def download(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> Response:
    """Zip of the latest iteration's recorded source files (final report, screen 7)."""
    task = _task(db, principal, task_id)
    iteration = _latest_iteration(db, task)
    if iteration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No files yet")
    base = workspace.iteration_dir(task.id, iteration.iteration_number)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a in _source_artifacts(db, iteration):
            try:
                z.writestr(a.file_name, workspace.read_file(base, a.file_name))
            except WorkspaceError:
                continue
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="task-{task.id}.zip"'},
    )


def _iteration(db: Session, task: Task, number: int) -> Iteration:
    it = db.scalars(
        select(Iteration).where(Iteration.task_id == task.id, Iteration.iteration_number == number)
    ).first()
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Iteration not found")
    return it


@router.get("/{task_id}/iterations/{number}/test-results", response_model=list[TestResultOut])
def test_results(
    task_id: uuid.UUID,
    number: int,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[TestResult]:
    it = _iteration(db, _task(db, principal, task_id), number)
    return sorted(it.test_results, key=lambda r: r.created_at)


@router.get("/{task_id}/iterations/{number}/logs", response_model=list[LogOut])
def logs(
    task_id: uuid.UUID,
    number: int,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[LogOut]:
    """Execution logs stored as artifacts (spec 3.6), with content, owner-scoped."""
    task = _task(db, principal, task_id)
    it = _iteration(db, task, number)
    base = workspace.log_dir(task.id, number)
    rows = db.scalars(
        select(Artifact).where(Artifact.iteration_id == it.id, Artifact.artifact_type == "log")
    )
    out: list[LogOut] = []
    for a in sorted(rows, key=lambda a: a.file_name):
        try:
            content = workspace.read_file(base, a.file_name)
        except WorkspaceError:
            continue
        out.append(LogOut(name=a.file_name, sha256=a.file_hash, content=content))
    return out


# ---- Phase 4: control + iteration history ------------------------------------------------


def _iteration_out(it: Iteration) -> IterationOut:
    fb = it.feedback
    return IterationOut(
        id=it.id,
        task_id=it.task_id,
        number=it.iteration_number,
        status=it.status,
        quality_score=it.quality_score,
        started_at=it.started_at,
        completed_at=it.completed_at,
        tests=fb.get("tests", {}),
        decision=fb.get("decision"),
        repair=fb.get("repair"),
    )


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel(
    task_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Task:
    """Stop a running task. The loop notices before its next step; an in-flight sandbox run is
    bounded by its timeout."""
    task = task_service.get_owned_task_for_update(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    try:
        task = task_service.transition(db, task, task_service.TaskStatus.CANCELLED)
    except task_service.InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="task.cancel",
        target_type="task", target_id=task.id, request=request,
    )  # fmt: skip
    set_etag(response, task.version)
    return task


@router.post("/{task_id}/retry", response_model=TaskOut)
def retry(
    task_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Task:
    """FAILED/ESCALATED -> PENDING. Call /start afterwards for a fresh run with a new budget."""
    task = task_service.get_owned_task_for_update(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    try:
        task = run_service.prepare_retry(db, task)
    except run_service.NotStartable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="task.retry",
        target_type="task", target_id=task.id, request=request,
    )  # fmt: skip
    set_etag(response, task.version)
    return task


@router.post("/{task_id}/resume", response_model=TaskOut, status_code=status.HTTP_202_ACCEPTED)
def resume(
    task_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Task:
    """Continue a run that was interrupted (e.g. the server restarted) from its checkpoint."""
    task = _task(db, principal, task_id)
    if task.id not in run_service.interrupted_task_ids(db):
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}; nothing to resume")
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="task.resume",
        target_type="task", target_id=task.id, request=request,
    )  # fmt: skip
    run_service.dispatch(background, factory, "resume", task.id, llm, sandbox)
    return task


@router.get("/{task_id}/iterations", response_model=list[IterationOut])
def list_iterations(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[IterationOut]:
    task = _task(db, principal, task_id)
    rows = db.scalars(
        select(Iteration).where(Iteration.task_id == task.id).order_by(Iteration.iteration_number)
    )
    return [_iteration_out(it) for it in rows]


def _owned_iteration(
    db: Session, principal: Principal, iteration_id: uuid.UUID
) -> tuple[Task, Iteration]:
    it = db.get(Iteration, iteration_id)
    task = task_service.get_owned_task(db, principal.org_id, it.task_id) if it else None
    if it is None or task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Iteration not found")
    return task, it


@iterations_router.get("/{iteration_id}", response_model=IterationDetailOut)
def iteration_detail(
    iteration_id: uuid.UUID,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> IterationDetailOut:
    _, it = _owned_iteration(db, principal, iteration_id)
    files = [
        FileOut(
            path=a.file_name,
            sha256=a.file_hash,
            iteration=it.iteration_number,
            created_at=a.created_at,
        )
        for a in _source_artifacts(db, it)
    ]
    results = sorted(it.test_results, key=lambda r: r.created_at)
    runs = sorted(it.agent_runs, key=lambda r: r.started_at)
    return IterationDetailOut(
        **_iteration_out(it).model_dump(),
        test_results=[TestResultOut.model_validate(r) for r in results],
        agent_runs=[AgentRunOut.model_validate(r) for r in runs],
        review=it.feedback.get("review"),
        quality=it.feedback.get("quality"),
        files=files,
    )


@iterations_router.get("/{iteration_id}/diff", response_model=IterationDiffOut)
def iteration_diff(
    iteration_id: uuid.UUID,
    against: uuid.UUID | None = None,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> IterationDiffOut:
    """Code changes of this iteration relative to the previous one (all files for the first), or
    relative to any other iteration of the same task via `?against=<iteration id>`."""
    task, it = _owned_iteration(db, principal, iteration_id)
    if against is not None:
        base = db.get(Iteration, against)
        if base is None or base.task_id != task.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Iteration not found")
    else:
        base = db.scalars(
            select(Iteration)
            .where(Iteration.task_id == task.id, Iteration.iteration_number < it.iteration_number)
            .order_by(Iteration.iteration_number.desc())
        ).first()
    base_number = base.iteration_number if base else None
    diffs = workspace.diff_iterations(task.id, base_number, it.iteration_number)
    return IterationDiffOut(
        iteration=it.iteration_number, against=base_number, files=[FileDiffOut(**d) for d in diffs]
    )


@iterations_router.get("/{iteration_id}/files/{file_path:path}", response_model=FileContentOut)
def iteration_file(
    iteration_id: uuid.UUID,
    file_path: str,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> FileContentOut:
    """Content of one recorded source file as it was in *this* iteration (code workspace)."""
    task, it = _owned_iteration(db, principal, iteration_id)
    known = {a.file_name: a for a in _source_artifacts(db, it)}
    if file_path not in known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    try:
        content = workspace.read_file(
            workspace.iteration_dir(task.id, it.iteration_number), file_path
        )
    except WorkspaceError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    return FileContentOut(path=file_path, sha256=known[file_path].file_hash, content=content)


@iterations_router.get("/{iteration_id}/logs", response_model=list[LogOut])
def iteration_logs(
    iteration_id: uuid.UUID,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[LogOut]:
    task, it = _owned_iteration(db, principal, iteration_id)
    return logs(task.id, it.iteration_number, principal, db)
