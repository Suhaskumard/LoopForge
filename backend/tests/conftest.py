import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_llm, get_sandbox
from app.config import settings
from app.database import session as session_module
from app.database.models import Base
from app.database.session import get_db, get_session_factory, make_engine
from app.execution.fake_sandbox import FakeSandbox
from app.main import app
from app.services.llm_client import FakeLLMClient

# Set TEST_DATABASE_URL (e.g. postgresql+psycopg://...) to run the whole suite on Postgres.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    """Every test writes generated code under its own temp directory."""
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspaces"))


def build_client(
    db_path,
    reset: bool = True,
    llm: FakeLLMClient | None = None,
    sandbox: FakeSandbox | None = None,
):
    url = TEST_DATABASE_URL or f"sqlite:///{db_path}"
    engine = make_engine(url)
    if TEST_DATABASE_URL and reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    fake = llm or FakeLLMClient()
    fake_sandbox = sandbox or FakeSandbox()

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_llm] = lambda: fake
    app.dependency_overrides[get_sandbox] = lambda: fake_sandbox
    session_module.engine = engine  # used by /health/ready
    client = TestClient(app)
    client.llm = fake
    client.sandbox = fake_sandbox
    client.factory = factory
    return client, engine


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path):
    c, engine = build_client(db_path)
    c.engine = engine
    yield c
    app.dependency_overrides.clear()
    engine.dispose()


def register_and_login(client: TestClient, email: str, password: str = "password123") -> dict:
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
