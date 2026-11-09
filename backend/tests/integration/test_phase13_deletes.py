# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: deleting projects, tasks and organizations leaves nothing behind and never trips a foreign key.

Found on a real PostgreSQL: `DELETE /projects/{id}` returned HTTP 500 (ForeignKeyViolation) when a task had an approval,
repair history, job, lease or publish request, because no ORM cascade reaches those tables. SQLite does not enforce
foreign keys by default, which is why every earlier test passed. These tests switch SQLite's enforcement ON so the
bug reproduces without PostgreSQL, and a structural test fails when a new table references tasks unhandled.
"""

import uuid

import pytest
from sqlalchemy import event, func, select

from app.database.models import (
    ApprovalRequest,
    Base,
    CodeComment,
    Job,
    Project,
    PublishRequest,
    RegressionWatch,
    RepairHistory,
    RunLease,
)
from app.services import retention_service
from tests.conftest import register_and_login

API = "/api/v1"


@pytest.fixture
def enforcing(client):
    """Turn SQLite's foreign-key enforcement on, as PostgreSQL always has it."""
    if client.engine.dialect.name != "sqlite":
        yield
        return

    @event.listens_for(client.engine, "connect")
    def _on(dbapi, _record):
        dbapi.execute("PRAGMA foreign_keys=ON")

    client.engine.dispose()  # new connections pick the pragma up
    yield
    event.remove(client.engine, "connect", _on)


def _task_with_dependents(client, h, project_id):
    task = client.post(
        f"{API}/tasks",
        json={"project_id": project_id, "requirement": "Build a small API with tests please."},
        headers=h,
    ).json()
    tid = uuid.UUID(task["id"])
    with client.factory() as db:
        db.add(
            ApprovalRequest(task_id=tid, kind="plan", status="approved", resume_status="PLANNING")
        )
        db.add(RepairHistory(task_id=tid, root_cause="r", proposed_fix="f", outcome="resolved"))
        db.add(
            RunLease(task_id=tid, owner="w", expires_at=__import__("datetime").datetime(2999, 1, 1))
        )
        db.add(Job(task_id=tid, kind="start", status="done"))
        db.add(
            PublishRequest(
                task_id=tid,
                org_id=db.get(Project, uuid.UUID(project_id)).org_id,
                repo="o/r",
                branch="loopforge/t",
                requested_by=uuid.uuid4(),
            )
        )
        project = db.get(Project, uuid.UUID(project_id))
        db.add(
            CodeComment(task_id=tid, user_id=project.user_id, file_path="app/x.py", line=1, body="n")
        )
        db.add(
            RegressionWatch(
                task_id=tid,
                org_id=project.org_id,
                interval_hours=24,
                next_run_at=__import__("datetime").datetime(2999, 1, 1),
                created_by=project.user_id,
            )
        )
        db.commit()
    return tid


def _remaining(client, tid):
    out = {}
    with client.factory() as db:
        for model in retention_service.TASK_DEPENDENTS:
            count = select(func.count()).select_from(model).where(model.task_id == tid)
            out[model.__tablename__] = db.scalar(count)
    return out


def test_deleting_a_project_removes_every_dependent_row_and_does_not_error(client, enforcing):
    h = register_and_login(client, "del@x.com")
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    tid = _task_with_dependents(client, h, p["id"])
    assert set(_remaining(client, tid).values()) == {1}  # every dependent table has a row to delete
    r = client.delete(f"{API}/projects/{p['id']}", headers=h)
    assert r.status_code == 204, r.text
    assert set(_remaining(client, tid).values()) == {0}
    assert client.get(f"{API}/tasks/{tid}", headers=h).status_code == 404


def test_deleting_a_project_also_removes_the_workspace_files(client, enforcing):
    h = register_and_login(client, "files@x.com")
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    tid = _task_with_dependents(client, h, p["id"])
    work = retention_service.workspace.workspace_root() / str(tid) / "iter_1"
    work.mkdir(parents=True)
    (work / "app.py").write_text("x = 1\n")
    assert client.delete(f"{API}/projects/{p['id']}", headers=h).status_code == 204
    assert not (retention_service.workspace.workspace_root() / str(tid)).exists()


def test_one_projects_delete_leaves_another_project_untouched(client, enforcing):
    h = register_and_login(client, "two@x.com")
    a = client.post(f"{API}/projects", json={"name": "a"}, headers=h).json()
    b = client.post(f"{API}/projects", json={"name": "b"}, headers=h).json()
    ta, tb = _task_with_dependents(client, h, a["id"]), _task_with_dependents(client, h, b["id"])
    assert client.delete(f"{API}/projects/{a['id']}", headers=h).status_code == 204
    assert set(_remaining(client, ta).values()) == {0}
    assert set(_remaining(client, tb).values()) == {1}  # the other project's rows are intact


def test_the_organization_data_delete_and_retention_paths_survive_foreign_keys(client, enforcing):
    h = register_and_login(client, "org@x.com")
    org = client.get(f"{API}/orgs", headers=h).json()[0]
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    tid = _task_with_dependents(client, h, p["id"])
    r = client.request(
        "DELETE", f"{API}/orgs/{org['id']}/data", json={"confirm": org["slug"]}, headers=h
    )
    assert r.status_code == 200 and r.json()["deleted_tasks"] == 1
    assert set(_remaining(client, tid).values()) == {0}


def test_every_table_that_references_tasks_is_handled():
    """Add a table with a foreign key to tasks.id? It must be cascaded by the ORM or listed in TASK_DEPENDENTS."""
    referencing = {
        table.name
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "tasks"
    }
    cascaded_by_the_orm = {"iterations", "audit_events", "requirements"}
    purged = {m.__tablename__ for m in retention_service.TASK_DEPENDENTS}
    assert referencing - cascaded_by_the_orm == purged, (
        f"unhandled tables: {referencing - cascaded_by_the_orm - purged}; "
        f"listed but not referencing tasks: {purged - referencing}"
    )
    assert (
        PublishRequest.__tablename__ in purged
    )  # the one Phase 11 added and Phase 12 retention missed
