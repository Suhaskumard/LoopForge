# ruff: noqa: E501
"""Phase 17: queue back-pressure - starts are refused (429 + Retry-After) while the queue is full."""

import pytest

from app.config import settings
from app.database.models import AuditLog, Job, Task
from app.utils.metrics import BACKPRESSURE
from tests.conftest import register_and_login

API = "/api/v1"


def make_task(client, h):
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    return client.post(
        f"{API}/tasks", json={"project_id": p["id"], "requirement": "Build employees"}, headers=h
    ).json()


@pytest.fixture
def queue_mode(monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "queue")
    monkeypatch.setattr(settings, "max_queued_jobs", 0)
    monkeypatch.setattr(settings, "max_queued_jobs_per_org", 0)


def start(client, h, task):
    return client.post(f"{API}/tasks/{task['id']}/start", headers=h)


def test_unlimited_by_default(client, queue_mode):
    h = register_and_login(client, "a@x.com")
    assert [start(client, h, make_task(client, h)).status_code for _ in range(3)] == [202] * 3


def test_global_cap_refuses_with_retry_after_and_leaves_the_task_startable(
    client, queue_mode, monkeypatch
):
    monkeypatch.setattr(settings, "max_queued_jobs", 2)
    monkeypatch.setattr(settings, "backpressure_retry_after_seconds", 17)
    h = register_and_login(client, "a@x.com")
    assert start(client, h, make_task(client, h)).status_code == 202
    assert start(client, h, make_task(client, h)).status_code == 202
    third = make_task(client, h)
    before = BACKPRESSURE.value(scope="global")
    r = start(client, h, third)
    assert r.status_code == 429 and r.headers["retry-after"] == "17"
    assert "job queue is full" in r.json()["error"]["message"]
    with client.factory() as db:
        assert db.query(Job).count() == 2  # nothing was enqueued
        assert db.get(Task, __import__("uuid").UUID(third["id"])).status == "PENDING"
        row = db.query(AuditLog).filter_by(action="queue.backpressure").one()
        assert row.detail["scope"] == "global"
    assert BACKPRESSURE.value(scope="global") == before + 1
    # capacity frees up -> the same task can start
    with client.factory() as db:
        db.query(Job).first().status = "done"
        db.commit()
    assert start(client, h, third).status_code == 202


def test_per_org_cap_isolates_a_noisy_tenant(client, queue_mode, monkeypatch):
    monkeypatch.setattr(settings, "max_queued_jobs_per_org", 1)
    noisy = register_and_login(client, "noisy@x.com")
    quiet = register_and_login(client, "quiet@x.com")
    assert start(client, noisy, make_task(client, noisy)).status_code == 202
    r = start(client, noisy, make_task(client, noisy))
    assert r.status_code == 429
    with client.factory() as db:
        assert (
            db.query(AuditLog).filter_by(action="queue.backpressure").one().detail["scope"] == "org"
        )
    assert start(client, quiet, make_task(client, quiet)).status_code == 202  # unaffected


def test_inline_mode_has_no_queue_so_no_back_pressure(client, monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "inline")
    monkeypatch.setattr(settings, "max_queued_jobs", 1)
    h = register_and_login(client, "a@x.com")
    assert start(client, h, make_task(client, h)).status_code == 202
    assert start(client, h, make_task(client, h)).status_code == 202


def test_metric_is_exposed_with_the_alertable_name():
    from app.utils.metrics import REGISTRY

    assert "loopforge_backpressure_total" in REGISTRY.render()
