"""Seed a demo user, project and task (idempotent). Run from backend/: python ../scripts/seed_database.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.database.models import Project, User  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.services import task_service  # noqa: E402
from app.utils.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@loopforge.local"
DEMO_REQUIREMENT = (
    "Develop a FastAPI-based employee management system with authentication, "
    "CRUD endpoints, input validation and unit tests."
)


def main() -> None:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.email == DEMO_EMAIL)).first()
        if user is None:
            user = User(email=DEMO_EMAIL, password_hash=hash_password("demo12345"))
            db.add(user)
            db.commit()
        project = db.scalars(select(Project).where(Project.user_id == user.id)).first()
        if project is None:
            project = Project(user_id=user.id, name="employee_management", language="python")
            db.add(project)
            db.commit()
            task_service.create_task(db, project, DEMO_REQUIREMENT, 5, [])
        print(f"Seeded {DEMO_EMAIL} / demo12345 with project '{project.name}'")


if __name__ == "__main__":
    main()
