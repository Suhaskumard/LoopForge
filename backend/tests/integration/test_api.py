from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditEvent
from tests.conftest import build_client, register_and_login


def make_project_and_task(client, headers):
    p = client.post("/api/v1/projects", json={"name": "emp"}, headers=headers).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": "Build employee API"},
        headers=headers,
    ).json()
    return p, t


def test_auth_flow(client):
    r = client.post("/api/v1/auth/register", json={"email": "A@x.com", "password": "password123"})
    assert r.status_code == 201
    assert "password" not in r.text
    dup = client.post("/api/v1/auth/register", json={"email": "a@x.com", "password": "password123"})
    assert dup.status_code == 409
    bad = client.post("/api/v1/auth/login", data={"username": "a@x.com", "password": "nope"})
    assert bad.status_code == 401
    headers = register_and_login(client, "a@x.com")
    assert client.get("/api/v1/auth/me", headers=headers).json()["email"] == "a@x.com"


def test_requires_auth(client):
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/tasks").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_project_crud(client):
    h = register_and_login(client, "a@x.com")
    p = client.post("/api/v1/projects", json={"name": "p1", "description": "d"}, headers=h).json()
    assert client.get("/api/v1/projects", headers=h).json()[0]["id"] == p["id"]
    up = client.put(f"/api/v1/projects/{p['id']}", json={"name": "p2"}, headers=h).json()
    assert up["name"] == "p2" and up["description"] == "d"
    assert client.delete(f"/api/v1/projects/{p['id']}", headers=h).status_code == 204
    assert client.get(f"/api/v1/projects/{p['id']}", headers=h).status_code == 404


def test_task_create_and_status(client):
    h = register_and_login(client, "a@x.com")
    _, t = make_project_and_task(client, h)
    assert t["status"] == "PENDING"
    assert client.get("/api/v1/tasks", headers=h).json()[0]["id"] == t["id"]
    assert client.get(f"/api/v1/tasks/{t['id']}", headers=h).status_code == 200


def test_invalid_status_transition_rejected(client, db_path):
    h = register_and_login(client, "a@x.com")
    _, t = make_project_and_task(client, h)
    bad = client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "COMPLETED"}, headers=h)
    assert bad.status_code == 409
    ok = client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "PLANNING"}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "PLANNING"
    assert client.get(f"/api/v1/tasks/{t['id']}", headers=h).json()["status"] == "PLANNING"


def test_status_change_writes_audit_event(client, db_path):
    h = register_and_login(client, "a@x.com")
    _, t = make_project_and_task(client, h)
    client.post(f"/api/v1/tasks/{t['id']}/status", json={"status": "PLANNING"}, headers=h)
    with Session(client.engine) as s:
        types = [e.event_type for e in s.scalars(select(AuditEvent))]
    assert types == ["task_created", "status_changed"]


def test_cross_user_isolation(client):
    ha = register_and_login(client, "a@x.com")
    hb = register_and_login(client, "b@x.com")
    p, t = make_project_and_task(client, ha)
    assert client.get(f"/api/v1/projects/{p['id']}", headers=hb).status_code == 404
    put = client.put(f"/api/v1/projects/{p['id']}", json={"name": "x"}, headers=hb)
    assert put.status_code == 404
    assert client.delete(f"/api/v1/projects/{p['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/tasks/{t['id']}", headers=hb).status_code == 404
    assert client.get("/api/v1/projects", headers=hb).json() == []
    assert client.get("/api/v1/tasks", headers=hb).json() == []
    assert (
        client.post(
            "/api/v1/tasks", json={"project_id": p["id"], "requirement": "x"}, headers=hb
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/tasks/{t['id']}/status", json={"status": "PLANNING"}, headers=hb
        ).status_code
        == 404
    )


def test_data_persists_across_restart(db_path):
    c1, e1 = build_client(db_path)
    h = register_and_login(c1, "a@x.com")
    p, t = make_project_and_task(c1, h)
    e1.dispose()
    # Simulate a service restart: brand-new engine/app wiring on the same DB file.
    c2, e2 = build_client(db_path)
    h2 = {"Authorization": h["Authorization"]}  # token is stateless, still valid
    assert c2.get(f"/api/v1/projects/{p['id']}", headers=h2).status_code == 200
    assert c2.get(f"/api/v1/tasks/{t['id']}", headers=h2).json()["requirement"] == (
        "Build employee API"
    )
    e2.dispose()
