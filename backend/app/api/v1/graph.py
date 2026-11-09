"""Workspace graph and repair memory (Round 8). Read-only; every query is org-scoped."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_viewer
from app.database.session import get_db
from app.schemas.graph import GraphOut, RepairOut
from app.services import graph_service

router = APIRouter(tags=["graph"])


@router.get("/graph", response_model=GraphOut)
def workspace_graph(
    principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> GraphOut:
    """Projects, tasks, failure classes and frequently repaired files, with how they connect."""
    return graph_service.build_graph(db, principal.org_id)


@router.get("/repairs", response_model=list[RepairOut])
def repair_memory(
    failure_class: str | None = Query(None, max_length=200),
    outcome: str | None = Query(None, max_length=40),
    limit: int = Query(200, ge=1, le=500),
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[RepairOut]:
    """What the repair agent tried and learned in this organization, newest first."""
    return graph_service.list_repairs(db, principal.org_id, failure_class, outcome, limit)
