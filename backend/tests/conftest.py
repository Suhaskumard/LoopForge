import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import session as session_module
from app.database.models import Base
from app.database.session import get_db, make_engine
from app.main import app

# Set TEST_DATABASE_URL (e.g. postgresql+psycopg://...) to run the whole suite on Postgres.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def build_client(db_path) -> tuple[TestClient, object]:
    url = TEST_DATABASE_URL or f"sqlite:///{db_path}"
    engine = make_engine(url)
    if TEST_DATABASE_URL:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    session_module.engine = engine  # used by /health/ready
    return TestClient(app), engine


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
