import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.etag import check_if_match, set_etag
from app.database.models import Project, User
from app.database.session import get_db
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _owned(db: Session, user: User, project_id: uuid.UUID) -> Project:
    project = project_service.get_project(db, user.id, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create(
    data: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Project:
    return project_service.create_project(db, user.id, data)


@router.get("", response_model=list[ProjectOut])
def list_all(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Project]:
    return project_service.list_projects(db, user.id, limit, offset)


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(
    project_id: uuid.UUID,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    project = _owned(db, user, project_id)
    set_etag(response, project.version)
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    response: Response,
    if_match: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    project = _owned(db, user, project_id)
    check_if_match(if_match, project.version)
    updated = project_service.update_project(db, project, data)
    set_etag(response, updated.version)
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    project_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    project_service.delete_project(db, _owned(db, user, project_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
