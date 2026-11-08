import time
import uuid

import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.database.models import Iteration, Requirement, Task
from tests.conftest import register_and_login


def _me(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code


def _project_and_task(client, h):
    p = client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks", json={"project_id": p["id"], "requirement": "r"}, headers=h
    ).json()
    return p, t


def test_login_rate_limited_after_repeated_failures(client):
    register_and_login(client, "rl@x.com")
    for _ in range(5):
        r = client.post("/api/v1/auth/login", data={"username": "rl@x.com", "password": "bad"})
        assert r.status_code == 401
    blocked = client.post("/api/v1/auth/login", data={"username": "rl@x.com", "password": "bad"})
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers
    # even the right password is refused while blocked
    good = client.post(
        "/api/v1/auth/login", data={"username": "rl@x.com", "password": "password123"}
    )
    assert good.status_code == 429


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={"email": "w@x.com", "password": "onlyletters"})
    assert r.status_code == 422
    r = client.post("/api/v1/auth/register", json={"email": "w@x.com", "password": "12345678"})
    assert r.status_code == 422


def test_pagination(client):
    h = register_and_login(client, "pg@x.com")
    for i in range(5):
        client.post("/api/v1/projects", json={"name": f"p{i}"}, headers=h)
    page1 = client.get("/api/v1/projects?limit=2&offset=0", headers=h).json()
    page2 = client.get("/api/v1/projects?limit=2&offset=2", headers=h).json()
    page3 = client.get("/api/v1/projects?limit=2&offset=4", headers=h).json()
    ids = [p["id"] for p in page1 + page2 + page3]
    assert len(ids) == 5 and len(set(ids)) == 5
    assert client.get("/api/v1/projects?limit=0", headers=h).status_code == 422
    assert client.get("/api/v1/projects?limit=201", headers=h).status_code == 422


def test_task_events_endpoint_and_isolation(client):
    ha = register_and_login(client, "a@x.com")
    hb = register_and_login(client, "b@x.com")
    _, t = _project_and_task(client, ha)
    client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "PLANNING"}, headers=ha)
    events = client.get(f"/api/v1/tasks/{t['id']}/events", headers=ha).json()
    assert [e["event_type"] for e in events] == ["task_created", "status_changed"]
    assert events[1]["event_data"] == {"from": "PENDING", "to": "PLANNING"}
    assert client.get(f"/api/v1/tasks/{t['id']}/events", headers=hb).status_code == 404


def test_db_rejects_invalid_status_value(client):
    h = register_and_login(client, "c@x.com")
    p, _ = _project_and_task(client, h)
    with Session(client.engine) as s:
        s.add(Task(project_id=uuid.UUID(p["id"]), requirement="x", status="BOGUS"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_db_unique_iteration_and_requirement_per_task(client):
    h = register_and_login(client, "d@x.com")
    _, t = _project_and_task(client, h)
    tid = uuid.UUID(t["id"])
    with Session(client.engine) as s:
        s.add(Iteration(task_id=tid, iteration_number=1))
        s.commit()
        s.add(Iteration(task_id=tid, iteration_number=1))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.add(Requirement(task_id=tid, req_id="REQ-1", description="a"))
        s.commit()
        s.add(Requirement(task_id=tid, req_id="REQ-1", description="b"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_deleting_project_cascades(client):
    h = register_and_login(client, "e@x.com")
    p, t = _project_and_task(client, h)
    assert client.delete(f"/api/v1/projects/{p['id']}", headers=h).status_code == 204
    assert client.get(f"/api/v1/tasks/{t['id']}", headers=h).status_code == 404
    with Session(client.engine) as s:
        assert s.scalar(text("select count(*) from tasks")) == 0


def test_security_headers_and_request_id(client):
    r = client.get("/health", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/health").headers["x-request-id"]  # generated when absent


def test_readiness_checks_database(client):
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_production_requires_strong_secret():
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret="change-me")
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret="short")
    Settings(  # ok (Phase 17: production also needs a separate encryption key)
        environment="production", jwt_secret="x" * 40, secrets_key="s" * 40, mail_backend="smtp"
    )
    Settings(environment="development")  # default secret allowed in dev


def test_expired_and_foreign_tokens_rejected(client):
    expired = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "exp": int(time.time()) - 10},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert _me(client, expired) == 401
    forged = jwt.encode({"sub": "x"}, "other-secret-other-secret-other-secret", algorithm="HS256")
    assert _me(client, forged) == 401
    unknown_user = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "exp": int(time.time()) + 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert _me(client, unknown_user) == 401
