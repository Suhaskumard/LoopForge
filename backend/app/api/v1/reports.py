"""Final report endpoints (spec 15.1, screen 7). Read-only; built from stored records."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_viewer
from app.database.session import get_db
from app.schemas.report import FinalReport
from app.services import report_service, task_service

router = APIRouter(prefix="/tasks", tags=["reports"])


def _report(db: Session, principal: Principal, task_id: uuid.UUID) -> FinalReport:
    task = task_service.get_owned_task(db, principal.org_id, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return report_service.build_report(db, task)


@router.get("/{task_id}/report", response_model=FinalReport)
def report(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> FinalReport:
    return _report(db, principal, task_id)


@router.get("/{task_id}/report.md")
def report_markdown(
    task_id: uuid.UUID, principal: Principal = Depends(get_viewer), db: Session = Depends(get_db)
) -> Response:
    r = _report(db, principal, task_id)
    body = report_service.render_markdown(r, report_service.read_readme(db, task_id))
    return Response(body, media_type="text/markdown; charset=utf-8")
