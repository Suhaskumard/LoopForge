import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def create_project(db: Session, user_id: uuid.UUID, data: ProjectCreate) -> Project:
    project = Project(user_id=user_id, **data.model_dump())
    db.add(project)
    db.commit()
    return project


def list_projects(
    db: Session, user_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(Project.created_at, Project.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_project(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> Project | None:
    stmt = select(Project).where(Project.id == project_id, Project.user_id == user_id)
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
