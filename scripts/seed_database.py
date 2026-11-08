"""Seed a demo user, project and task (idempotent). Run from backend/: python ../scripts/seed_database.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.database.models import Project, User  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.services import org_service, task_service  # noqa: E402
from app.utils.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@example.com"
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
        ctx = org_service.resolve(db, user.id, None)
        org_id = ctx.org_id if ctx else org_service.create_personal_org(db, user).id
        project = db.scalars(select(Project).where(Project.org_id == org_id)).first()
        if project is None:
            project = Project(
                user_id=user.id, org_id=org_id, name="employee_management", language="python"
            )
            db.add(project)
            db.commit()
            task_service.create_task(db, project, DEMO_REQUIREMENT, 5, [])
        print(f"Seeded {DEMO_EMAIL} / demo12345 with project '{project.name}'")


if __name__ == "__main__":
    main()
