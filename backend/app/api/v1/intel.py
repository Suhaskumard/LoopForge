"""Round 9 "loop intelligence": forecast, code comments for the Repair agent, regression watch and
A/B model experiments. Every query is scoped to the caller's organization."""

import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import Principal, get_developer, get_llm, get_sandbox, get_viewer
from app.database.models import CodeComment, RegressionWatch, Task, User
from app.database.session import get_db, get_session_factory
from app.execution.sandbox import Sandbox
from app.schemas.intel import (
    CodeCommentCreate,
    CodeCommentOut,
    CodeCommentUpdate,
    ExperimentCreate,
    ExperimentOut,
    ForecastOut,
    RerunOut,
    VariantOut,
    WatchIn,
    WatchOut,
    WatchStatus,
)
from app.schemas.task import TaskOut
from app.services import audit_service, intel_service, run_service, task_service
from app.services.llm_client import LLMClient

router = APIRouter(tags=["intelligence"])


def _task(db: Session, p: Principal, task_id: uuid.UUID) -> Task:
    task = task_service.get_owned_task(db, p.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


def _starter(
    background: BackgroundTasks,
    factory: sessionmaker[Session],
    llm: LLMClient,
    sandbox: Sandbox,
) -> intel_service.Starter:
    def start(task_id: uuid.UUID) -> None:
        run_service.dispatch(background, factory, "start", task_id, llm, sandbox)

    return start


def _fail(exc: Exception) -> HTTPException:
    code = status.HTTP_409_CONFLICT
    if isinstance(exc, intel_service.IntelError) and "must be" in str(exc):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(code, str(exc))


# ---- 1. forecast --------------------------------------------------------------------------------


@router.get("/forecast", response_model=ForecastOut)
def forecast(
    language: str = Query("python", pattern=r"^[a-z]{2,20}$"),
    words: int = Query(0, ge=0, le=5000),
    p: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Tokens, cost, rounds and time that finished tasks like this one took (p50/p90)."""
    return intel_service.forecast(db, p.org_id, language, words)


# ---- 2. code comments read by the Repair agent ---------------------------------------------------


def _comment_out(db: Session, c: CodeComment) -> CodeCommentOut:
    author = db.get(User, c.user_id)
    out = CodeCommentOut.model_validate(c)
    out.author = author.email if author else ""
    return out


@router.get("/tasks/{task_id}/comments", response_model=list[CodeCommentOut])
def list_comments(
    task_id: uuid.UUID, p: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[CodeCommentOut]:
    task = _task(db, p, task_id)
    rows = db.scalars(
        select(CodeComment).where(CodeComment.task_id == task.id).order_by(CodeComment.created_at)
    )
    return [_comment_out(db, c) for c in rows]


@router.post(
    "/tasks/{task_id}/comments", response_model=CodeCommentOut, status_code=status.HTTP_201_CREATED
)
def add_comment(
    task_id: uuid.UUID,
    data: CodeCommentCreate,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> CodeCommentOut:
    """A note on a line of code. Unresolved notes reach the Repair agent as (untrusted) hints."""
    task = _task(db, p, task_id)
    c = CodeComment(
        task_id=task.id, user_id=p.user.id, file_path=data.file_path, line=data.line,
        body=data.body.strip(), iteration_number=data.iteration_number,
    )  # fmt: skip
    db.add(c)
    db.commit()
    db.refresh(c)
    return _comment_out(db, c)


@router.patch("/tasks/{task_id}/comments/{comment_id}", response_model=CodeCommentOut)
def update_comment(
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
    data: CodeCommentUpdate,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> CodeCommentOut:
    task = _task(db, p, task_id)
    c = db.get(CodeComment, comment_id)
    if c is None or c.task_id != task.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    c.resolved = data.resolved
    db.commit()
    db.refresh(c)
    return _comment_out(db, c)


# ---- 3. regression watch ------------------------------------------------------------------------


def _watch_status(db: Session, task: Task) -> WatchStatus:
    watch = db.scalars(select(RegressionWatch).where(RegressionWatch.task_id == task.id)).first()
    reruns = db.scalars(
        select(Task)
        .where(Task.rerun_of == task.id, Task.experiment.is_(None))
        .order_by(Task.created_at.desc())
        .limit(10)
    )
    return WatchStatus(
        watch=WatchOut.model_validate(watch) if watch else None,
        reruns=[RerunOut.model_validate(t) for t in reruns],
    )


@router.get("/tasks/{task_id}/watch", response_model=WatchStatus)
def get_watch(
    task_id: uuid.UUID, p: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> WatchStatus:
    return _watch_status(db, _task(db, p, task_id))


@router.put("/tasks/{task_id}/watch", response_model=WatchStatus)
def set_watch(
    task_id: uuid.UUID,
    data: WatchIn,
    request: Request,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> WatchStatus:
    """Re-run this accepted task daily (24) or weekly (168) and alert when it stops passing."""
    task = _task(db, p, task_id)
    try:
        intel_service.set_watch(db, task, p.org_id, data.interval_hours, data.active, p.user.id)
    except intel_service.IntelError as exc:
        raise _fail(exc) from None
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="task.watch",
        target_type="task", target_id=task.id,
        detail={"interval_hours": data.interval_hours, "active": data.active}, request=request,
    )  # fmt: skip
    return _watch_status(db, task)


@router.delete("/tasks/{task_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def delete_watch(
    task_id: uuid.UUID, p: Principal = Depends(get_developer), db: Session = Depends(get_db)
) -> None:
    task = _task(db, p, task_id)
    watch = db.scalars(select(RegressionWatch).where(RegressionWatch.task_id == task.id)).first()
    if watch is not None:
        db.delete(watch)
        db.commit()


@router.post("/tasks/{task_id}/rerun", response_model=TaskOut, status_code=status.HTTP_202_ACCEPTED)
def rerun(
    task_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Task:
    """Regression check now: a fresh copy of this accepted task runs from scratch."""
    task = _task(db, p, task_id)
    try:
        clone = intel_service.rerun(
            db, task, p.user.id, _starter(background, factory, llm, sandbox)
        )
    except (intel_service.IntelError, run_service.NotStartable) as exc:
        raise _fail(exc) from None
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="task.rerun",
        target_type="task", target_id=task.id, detail={"rerun": str(clone.id)}, request=request,
    )  # fmt: skip
    return clone


# ---- 5. A/B model experiments -------------------------------------------------------------------


@router.post(
    "/tasks/{task_id}/experiments",
    response_model=ExperimentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_experiment(
    task_id: uuid.UUID,
    data: ExperimentCreate,
    background: BackgroundTasks,
    request: Request,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ExperimentOut:
    """Run this task twice, with a different model for one agent, and compare the runs."""
    task = _task(db, p, task_id)
    try:
        experiment, _ = intel_service.start_experiment(
            db, task, data.agent, data.model_a, data.model_b, p.user.id,
            _starter(background, factory, llm, sandbox),
        )  # fmt: skip
    except (intel_service.IntelError, run_service.NotStartable) as exc:
        raise _fail(exc) from None
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="task.experiment",
        target_type="task", target_id=task.id,
        detail={"experiment": experiment, "agent": data.agent}, request=request,
    )  # fmt: skip
    return ExperimentOut(
        experiment=experiment,
        variants=[VariantOut(**v) for v in intel_service.experiment_rows(db, p.org_id, experiment)],
    )


@router.get("/experiments/{experiment}", response_model=ExperimentOut)
def get_experiment(
    experiment: str = Path(..., pattern=r"^[a-f0-9]{12}$"),
    p: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> ExperimentOut:
    rows = intel_service.experiment_rows(db, p.org_id, experiment)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experiment not found")
    return ExperimentOut(experiment=experiment, variants=[VariantOut(**v) for v in rows])
