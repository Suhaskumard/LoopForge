"""Round 12: failure explanations, auto pipelines and smart model routing."""

import re
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    Principal,
    get_developer,
    get_llm,
    get_sandbox,
    get_viewer,
    require_org_role,
)
from app.database.models import Organization, Pipeline, Task
from app.database.session import get_db, get_session_factory
from app.execution.sandbox import Sandbox
from app.schemas.advanced import (
    MODEL_NAME,
    Explanation,
    PipelineCreate,
    PipelineOut,
    RoutingIn,
    RoutingOut,
    StepOut,
)
from app.schemas.task import TaskOut
from app.services import (
    audit_service,
    explain_service,
    pipeline_service,
    project_service,
    routing_service,
    run_service,
    task_service,
)
from app.services.llm_client import LLMClient

router = APIRouter(tags=["advanced"])
org_viewer = require_org_role("viewer")
org_admin = require_org_role("admin")


def _task(db: Session, p: Principal, task_id: uuid.UUID) -> Task:
    task = task_service.get_owned_task(db, p.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


def _starter(
    background: BackgroundTasks, factory: sessionmaker[Session], llm: LLMClient, sandbox: Sandbox
) -> Any:
    def start(task_id: uuid.UUID) -> None:
        run_service.dispatch(background, factory, "start", task_id, llm, sandbox)

    return start


# ---- 1. failure explainer ------------------------------------------------------------------------


@router.get("/tasks/{task_id}/explanation", response_model=Explanation | None)
def get_explanation(
    task_id: uuid.UUID, p: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> Explanation | None:
    return explain_service.stored(db, _task(db, p, task_id))


@router.post("/tasks/{task_id}/explanation", response_model=Explanation)
def explain(
    task_id: uuid.UUID,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
) -> Explanation:
    """Why the run was not accepted and what to change: AI-written when a model is available,
    otherwise composed from the stored evidence (labelled `source`)."""
    try:
        return explain_service.explain(db, _task(db, p, task_id), llm)
    except explain_service.ExplainError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.post(
    "/tasks/{task_id}/explanation/apply",
    response_model=TaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_with_fix(
    task_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> Task:
    """Hand the suggested fix to the Repair agent (as a note) and run the task again."""
    task = _task(db, p, task_id)
    try:
        explain_service.add_retry_note(db, task, p.user.id)
        run_service.prepare_retry(db, task)
        run_service.prepare_start(db, task)
    except (explain_service.ExplainError, run_service.NotStartable) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="task.retry_with_fix",
        target_type="task", target_id=task.id, request=request,
    )  # fmt: skip
    run_service.dispatch(background, factory, "start", task.id, llm, sandbox)
    return task


# ---- 2. pipelines --------------------------------------------------------------------------------


def _pipeline_out(db: Session, pl: Pipeline) -> PipelineOut:
    out = PipelineOut.model_validate(pl)
    steps = []
    for s in pl.steps:
        so = StepOut.model_validate(s)
        if s.task_id is not None:
            t = db.get(Task, s.task_id)
            so.task_status = t.status if t is not None else None
        steps.append(so)
    out.steps = steps
    return out


def _pipeline(db: Session, p: Principal, pipeline_id: uuid.UUID) -> Pipeline:
    pl = db.get(Pipeline, pipeline_id)
    if pl is None or pl.org_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    return pl


@router.post("/pipelines", response_model=PipelineOut, status_code=status.HTTP_201_CREATED)
def create_pipeline(
    data: PipelineCreate, p: Principal = Depends(get_developer), db: Session = Depends(get_db)
) -> PipelineOut:
    project = project_service.get_project(db, p.org_id, data.project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    pl = pipeline_service.create(db, p.org_id, project, data.name, data.steps, p.user.id)
    return _pipeline_out(db, pl)


@router.get("/pipelines", response_model=list[PipelineOut])
def list_pipelines(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[PipelineOut]:
    rows = db.scalars(
        select(Pipeline)
        .where(Pipeline.org_id == p.org_id)
        .order_by(Pipeline.created_at.desc(), Pipeline.id)
        .limit(limit)
        .offset(offset)
    )
    return [_pipeline_out(db, pl) for pl in rows]


@router.get("/pipelines/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(
    pipeline_id: uuid.UUID, p: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> PipelineOut:
    return _pipeline_out(db, _pipeline(db, p, pipeline_id))


@router.post("/pipelines/{pipeline_id}/start", response_model=PipelineOut)
def start_pipeline(
    pipeline_id: uuid.UUID,
    background: BackgroundTasks,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> PipelineOut:
    """Run step 1; each accepted step then starts the next from its code, automatically."""
    pl = _pipeline(db, p, pipeline_id)
    try:
        pl = pipeline_service.start(db, pl, p.user.id, _starter(background, factory, llm, sandbox))
    except (pipeline_service.PipelineError, run_service.NotStartable) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _pipeline_out(db, pl)


@router.post("/pipelines/{pipeline_id}/pause", response_model=PipelineOut)
def pause_pipeline(
    pipeline_id: uuid.UUID, p: Principal = Depends(get_developer), db: Session = Depends(get_db)
) -> PipelineOut:
    """The running step finishes; the next one waits for `resume`."""
    try:
        pl = pipeline_service.pause(db, _pipeline(db, p, pipeline_id))
    except pipeline_service.PipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _pipeline_out(db, pl)


@router.post("/pipelines/{pipeline_id}/resume", response_model=PipelineOut)
def resume_pipeline(
    pipeline_id: uuid.UUID,
    background: BackgroundTasks,
    p: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> PipelineOut:
    """Retry the step that failed (or start the next one if it was accepted meanwhile)."""
    pl = _pipeline(db, p, pipeline_id)
    try:
        pl = pipeline_service.resume(db, pl, p.user.id, _starter(background, factory, llm, sandbox))
    except (pipeline_service.PipelineError, run_service.NotStartable) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _pipeline_out(db, pl)


# ---- 3. model routing ----------------------------------------------------------------------------


@router.get("/orgs/{org_id}/routing", response_model=RoutingOut)
def get_routing(p: Principal = Depends(org_viewer), db: Session = Depends(get_db)) -> RoutingOut:
    st = routing_service.stats(db, p.org_id)
    return RoutingOut(
        routing=routing_service.routing_for(db, p.org_id),
        stats=st,
        recommendations=routing_service.recommend(st),
        window_days=routing_service.WINDOW_DAYS,
    )


@router.put("/orgs/{org_id}/routing", response_model=RoutingOut)
def put_routing(
    data: RoutingIn,
    request: Request,
    p: Principal = Depends(org_admin),
    db: Session = Depends(get_db),
) -> RoutingOut:
    """Organization-wide model per agent. A task's own A/B override still wins."""
    for model in data.routing.values():
        if model and not re.match(MODEL_NAME, model):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid model name {model!r}"
            )
    org = db.get(Organization, p.org_id)
    if org is None:  # the dependency already resolved it; only a concurrent delete gets here
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    try:
        routing_service.set_routing(db, org, data.routing)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    audit_service.record(
        db, org_id=p.org_id, actor_id=p.user.id, action="org.routing",
        target_type="organization", target_id=p.org_id, detail={"routing": org.model_routing},
        request=request,
    )  # fmt: skip
    return get_routing(p, db)
