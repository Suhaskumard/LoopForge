import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def create_project(
    db: Session, org_id: uuid.UUID, created_by: uuid.UUID, data: ProjectCreate
) -> Project:
    project = Project(org_id=org_id, user_id=created_by, **data.model_dump())
    db.add(project)
    db.commit()
    return project


def list_projects(
    db: Session, org_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.org_id == org_id)
        .order_by(Project.created_at, Project.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_project(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> Project | None:
    stmt = select(Project).where(Project.id == project_id, Project.org_id == org_id)
    return db.scalars(stmt).first()


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, key, value)
    db.commit()
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.commit()
