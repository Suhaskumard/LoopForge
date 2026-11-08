"""Analytics APIs (spec §8). Every figure comes from services/analytics_service.py."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_viewer
from app.database.models import Iteration
from app.database.session import get_db
from app.schemas.analytics import (
    AgentStatOut,
    IterationAnalyticsOut,
    OverviewOut,
    TaskAnalyticsOut,
)
from app.services import analytics_service, task_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewOut)
def overview(
    principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> OverviewOut:
    return analytics_service.overview(db, principal.org_id)


@router.get("/tasks/{task_id}", response_model=TaskAnalyticsOut)
def task_analytics(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> TaskAnalyticsOut:
    task = task_service.get_owned_task(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return analytics_service.task_analytics(db, task)


@router.get("/iterations/{iteration_id}", response_model=IterationAnalyticsOut)
def iteration_analytics(
    iteration_id: uuid.UUID,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> IterationAnalyticsOut:
    it = db.get(Iteration, iteration_id)
    task = task_service.get_owned_task(db, principal.org_id, it.task_id) if it else None
    if it is None or task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Iteration not found")
    return analytics_service.iteration_analytics(db, it)


@router.get("/agents", response_model=list[AgentStatOut])
def agents(
    principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> list[AgentStatOut]:
    return analytics_service.agent_analytics(db, principal.org_id)
