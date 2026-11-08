import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_developer, get_viewer
from app.api.etag import check_if_match, set_etag
from app.database.models import Project
from app.database.session import get_db
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import audit_service, project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _owned(db: Session, principal: Principal, project_id: uuid.UUID) -> Project:
    project = project_service.get_project(db, principal.org_id, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create(
    data: ProjectCreate,
    request: Request,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Project:
    project = project_service.create_project(db, principal.org_id, principal.user.id, data)
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="project.create",
        target_type="project", target_id=project.id, detail={"name": project.name}, request=request,
    )  # fmt: skip
    return project


@router.get("", response_model=list[ProjectOut])
def list_all(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> list[Project]:
    return project_service.list_projects(db, principal.org_id, limit, offset)


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(
    project_id: uuid.UUID,
    response: Response,
    principal: Principal = Depends(get_viewer),
    db: Session = Depends(get_db),
) -> Project:
    project = _owned(db, principal, project_id)
    set_etag(response, project.version)
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Project:
    project = _owned(db, principal, project_id)
    check_if_match(if_match, project.version)
    updated = project_service.update_project(db, project, data)
    set_etag(response, updated.version)
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    project_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_developer),
    db: Session = Depends(get_db),
) -> Response:
    project_service.delete_project(db, _owned(db, principal, project_id))
    audit_service.record(
        db, org_id=principal.org_id, actor_id=principal.user.id, action="project.delete",
        target_type="project", target_id=project_id, request=request,
    )  # fmt: skip
    return Response(status_code=status.HTTP_204_NO_CONTENT)
