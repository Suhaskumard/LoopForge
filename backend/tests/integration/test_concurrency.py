import uuid

from sqlalchemy.orm import Session

from app.database.models import Project
from tests.conftest import register_and_login


def _project(client, h):
    return client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()


def test_etag_on_get_and_if_match_flow(client):
    h = register_and_login(client, "e@x.com")
    p = _project(client, h)
    g = client.get(f"/api/v1/projects/{p['id']}", headers=h)
    etag = g.headers["etag"]
    assert etag == '"1"'
    ok = client.put(
        f"/api/v1/projects/{p['id']}", json={"name": "v2"}, headers={**h, "If-Match": etag}
    )
    assert ok.status_code == 200 and ok.headers["etag"] == '"2"' and ok.json()["version"] == 2
    stale = client.put(
        f"/api/v1/projects/{p['id']}", json={"name": "v3"}, headers={**h, "If-Match": etag}
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "precondition_failed"
    # no If-Match header still works (opt-in precondition)
    assert (
        client.put(f"/api/v1/projects/{p['id']}", json={"name": "v4"}, headers=h).status_code == 200
    )


def test_task_if_match_on_status_change(client):
    h = register_and_login(client, "t@x.com")
    p = _project(client, h)
    t = client.post(
        "/api/v1/tasks", json={"project_id": p["id"], "requirement": "r"}, headers=h
    ).json()
    etag = client.get(f"/api/v1/tasks/{t['id']}", headers=h).headers["etag"]
    first = client.post(
        f"/api/v1/tasks/{t['id']}/status",
        json={"status": "PLANNING"},
        headers={**h, "If-Match": etag},
    )
    assert first.status_code == 200 and first.json()["version"] == 2
    replay = client.post(
        f"/api/v1/tasks/{t['id']}/status",
        json={"status": "GENERATING"},
        headers={**h, "If-Match": etag},
    )
    assert replay.status_code == 412


def test_concurrent_writer_detected_as_409(client):
    """Two sessions load the same row; the second flush must fail, not silently overwrite."""
    h = register_and_login(client, "c@x.com")
    p = _project(client, h)
    pid = uuid.UUID(p["id"])
    with Session(client.engine) as s1, Session(client.engine) as s2:
        a, b = s1.get(Project, pid), s2.get(Project, pid)
        a.name = "from-s1"
        s1.commit()
        b.name = "from-s2"
        import pytest
        from sqlalchemy.orm.exc import StaleDataError

        with pytest.raises(StaleDataError):
            s2.commit()
