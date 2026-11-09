"""Round 8: workspace graph, repair memory and newest-first task listing."""

import uuid
from datetime import datetime, timedelta

from app.database.models import Iteration, RepairHistory, Task
from tests.conftest import register_and_login

API = "/api/v1"


def _task(client, h, project_id, requirement, **extra):
    r = client.post(
        f"{API}/tasks",
        json={"project_id": project_id, "requirement": requirement, **extra},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _project(client, h, name="graph_proj"):
    return client.post(f"{API}/projects", json={"name": name}, headers=h).json()["id"]


def _repair(db, tid, *, fingerprint, outcome, failure_class="assertion", files=("app/a.py",), at):
    db.add(
        RepairHistory(
            task_id=uuid.UUID(tid),
            failure_class=failure_class,
            fingerprint=fingerprint,
            root_cause="off by one",
            proposed_fix="use < not <=",
            files_modified=list(files),
            outcome=outcome,
            tokens_used=120,
            created_at=at,
        )
    )


def _seed(client, h):
    pid = _project(client, h)
    a = _task(client, h, pid, "Build an API A with tests")
    b = _task(client, h, pid, "Build an API B with tests")
    c = _task(client, h, pid, "Build an API C with tests", learn_from_task=False)
    d = _task(client, h, pid, "Build an API D with tests")
    t0 = datetime(2026, 1, 1)
    with client.factory() as db:
        _repair(db, a, fingerprint="fp1", outcome="resolved", at=t0)
        _repair(db, b, fingerprint="fp1", outcome="resolved", at=t0 + timedelta(minutes=1))
        _repair(db, c, fingerprint="fp2", outcome="resolved", failure_class="import", at=t0)
        _repair(db, d, fingerprint="fp2", outcome="unresolved", failure_class="import",
                files=("app/b.py",), at=t0 + timedelta(minutes=2))  # fmt: skip
        db.add(Iteration(task_id=uuid.UUID(a), iteration_number=1, quality_score=55.0))
        db.add(Iteration(task_id=uuid.UUID(a), iteration_number=2, quality_score=91.0))
        db.commit()
    return pid, a, b, c, d


def test_graph_has_projects_tasks_failures_files_and_learning_links(client):
    h = register_and_login(client, "graph@x.com")
    pid, a, b, c, d = _seed(client, h)
    g = client.get(f"{API}/graph", headers=h).json()
    ids = {n["id"]: n for n in g["nodes"]}
    assert ids[f"p:{pid}"]["meta"]["tasks"] == 4
    assert ids[f"t:{a}"]["meta"]["quality"] == 91.0  # latest iteration wins
    assert ids["f:assertion"]["meta"] == {"count": 2, "resolved": 2}
    assert ids["f:import"]["meta"] == {"count": 2, "resolved": 1}
    assert "file:app/a.py" in ids and "file:app/b.py" in ids
    edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    assert (f"p:{pid}", f"t:{a}", "contains") in edges
    assert (f"t:{a}", "f:assertion", "failed_with") in edges
    assert (f"t:{d}", "file:app/b.py", "touched") in edges
    # b reused a's resolved fix; d could not learn from c, which opted out
    assert (f"t:{b}", f"t:{a}", "learned_from") in edges
    assert not any(k == "learned_from" and s == f"t:{d}" for s, _, k in edges)
    assert g["truncated"] is False


def test_graph_and_repairs_never_show_another_organizations_data(client):
    ha = register_and_login(client, "orga@x.com")
    _seed(client, ha)
    hb = register_and_login(client, "orgb@x.com")
    assert client.get(f"{API}/graph", headers=hb).json() == {
        "nodes": [],
        "edges": [],
        "truncated": False,
    }
    assert client.get(f"{API}/repairs", headers=hb).json() == []


def test_repairs_list_newest_first_with_filters(client):
    h = register_and_login(client, "repairs@x.com")
    _, a, b, c, d = _seed(client, h)
    rows = client.get(f"{API}/repairs", headers=h).json()
    assert [r["task_id"] for r in rows][0] == d  # newest first
    assert len(rows) == 4
    imports = client.get(f"{API}/repairs", params={"failure_class": "import"}, headers=h).json()
    assert {r["task_id"] for r in imports} == {c, d}
    assert next(r for r in imports if r["task_id"] == c)["learnable"] is False
    resolved = client.get(f"{API}/repairs", params={"outcome": "resolved"}, headers=h).json()
    assert {r["task_id"] for r in resolved} == {a, b, c}


def test_task_list_can_be_newest_first_and_defaults_to_oldest(client):
    h = register_and_login(client, "order@x.com")
    pid = _project(client, h)
    first = _task(client, h, pid, "first task here")
    second = _task(client, h, pid, "second task here")
    with client.factory() as db:  # make the order unambiguous regardless of clock resolution
        db.get(Task, uuid.UUID(first)).created_at = datetime(2026, 1, 1)
        db.get(Task, uuid.UUID(second)).created_at = datetime(2026, 1, 2)
        db.commit()
    asc = [t["id"] for t in client.get(f"{API}/tasks", headers=h).json()]
    desc = [t["id"] for t in client.get(f"{API}/tasks", params={"order": "desc"}, headers=h).json()]
    assert asc == [first, second]
    assert desc == [second, first]
    assert client.get(f"{API}/tasks", params={"order": "sideways"}, headers=h).status_code == 422
