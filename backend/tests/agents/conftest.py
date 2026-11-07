import pytest
from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.database.models import Base, Iteration, Project, Task, User
from app.database.session import make_engine
from app.services.llm_client import FakeLLMClient
from app.utils.token_tracker import TokenTracker

REQUIREMENT = "Develop a FastAPI-based employee management system with auth, CRUD and tests."


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'agents.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s
    engine.dispose()


@pytest.fixture
def llm():
    return FakeLLMClient()


@pytest.fixture
def ctx(db, llm):
    user = User(email="a@x.com", password_hash="x")
    db.add(user)
    db.flush()
    project = Project(user_id=user.id, name="p")
    db.add(project)
    db.flush()
    task = Task(
        project_id=project.id,
        requirement=REQUIREMENT,
        acceptance_criteria=["User supplied criterion"],
    )
    db.add(task)
    db.flush()
    iteration = Iteration(task_id=task.id, iteration_number=1)
    db.add(iteration)
    db.commit()
    return AgentContext(
        db=db, task=task, iteration=iteration, llm=llm, tracker=TokenTracker(30_000)
    )
