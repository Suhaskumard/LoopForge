"""Phase 7: cross-process leases, the job queue + worker, and trusted-proxy client IPs."""

import threading
import uuid
from datetime import timedelta

from starlette.requests import Request

from app.config import settings
from app.database.models import Job, RunLease, Task
from app.demo.employee_management import failing_update_report, passing_report_for_demo
from app.execution.fake_sandbox import ScriptedSandbox
from app.services import job_service, lease_service, run_service
from app.utils.client_ip import client_ip
from app.worker import run_once
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import HAPPY_LLM


def _task(client, h):
    p = client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()
    return client.post(
        "/api/v1/tasks", json={"project_id": p["id"], "requirement": "Build employees"}, headers=h
    ).json()


# ---- leases -------------------------------------------------------------------------------


def test_lease_is_exclusive_until_expiry_then_taken_over(client):
    h = register_and_login(client, "l@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    with client.factory() as a, client.factory() as b:
        assert lease_service.acquire(a, tid, owner="A", ttl=30)
        assert not lease_service.acquire(b, tid, owner="B", ttl=30)
        assert lease_service.acquire(a, tid, owner="A", ttl=30)  # re-entrant for the owner
        assert not lease_service.renew(b, tid, owner="B")
        # the owner dies: its lease lapses and another process may take over
        a.query(RunLease).update({"expires_at": run_service._now() - timedelta(seconds=1)})
        a.commit()
        assert not lease_service.is_held(a, tid)
        assert lease_service.acquire(b, tid, owner="B", ttl=30)
        assert lease_service.is_held(a, tid)
        lease_service.release(a, tid, owner="A")  # not the owner: no effect
        assert lease_service.is_held(b, tid)
        lease_service.release(b, tid, owner="B")
        assert not lease_service.is_held(b, tid)


def test_only_one_of_many_concurrent_claimants_wins(client):
    h = register_and_login(client, "c@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    wins: list[str] = []

    def claim(name: str) -> None:
        with client.factory() as db:
            if lease_service.acquire(db, tid, owner=name, ttl=30):
                wins.append(name)

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(wins) == 1


def test_a_run_is_refused_while_another_process_holds_the_lease(client):
    h = register_and_login(client, "r@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    with client.factory() as db:
        assert lease_service.acquire(db, tid, owner="other-process", ttl=60)
    assert run_service.resume_run(client.factory, tid, client.llm, client.sandbox) is False
    with client.factory() as db:  # the foreign lease is untouched
        assert db.get(RunLease, tid).owner == "other-process"


def test_heartbeat_keeps_lease_alive_and_flags_a_lost_one(client, monkeypatch):
    h = register_and_login(client, "hb@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    monkeypatch.setattr(settings, "lease_ttl_seconds", 0.3)
    with client.factory() as db:
        assert lease_service.acquire(db, tid)
    with lease_service.Heartbeat(client.factory, tid) as hb:
        threading.Event().wait(0.6)  # longer than the ttl: only renewal keeps it valid
        with client.factory() as db:
            assert lease_service.is_held(db, tid)
        with client.factory() as db:
            db.query(RunLease).delete()
            db.commit()
        threading.Event().wait(0.3)
    assert hb.lost


# ---- queue + worker -----------------------------------------------------------------------


def test_queue_mode_enqueues_and_a_worker_runs_the_loop(client, monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "queue")
    client.llm.queue(*HAPPY_LLM)
    sandbox = ScriptedSandbox([failing_update_report(), passing_report_for_demo()])
    h = register_and_login(client, "q@x.com")
    t = _task(client, h)
    r = client.post(f"/api/v1/tasks/{t['id']}/start", headers=h)
    assert r.status_code == 202
    with client.factory() as db:
        jobs = db.query(Job).all()
        assert [(j.kind, j.status) for j in jobs] == [("start", "queued")]
        assert db.get(Task, uuid.UUID(t["id"])).current_iteration == 0  # API did not run it
    assert run_once(client.factory, client.llm, sandbox, worker="w1") is True
    assert run_once(client.factory, client.llm, sandbox, worker="w1") is False
    with client.factory() as db:
        job = db.query(Job).one()
        assert job.status == "done" and job.claimed_by == "w1"
        assert db.get(Task, uuid.UUID(t["id"])).status == "COMPLETED"
        assert db.query(RunLease).count() == 0  # released


def test_enqueue_is_idempotent_and_claim_is_exclusive(client):
    h = register_and_login(client, "e@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    with client.factory() as db:
        a = job_service.enqueue(db, tid, "start")
        b = job_service.enqueue(db, tid, "start")
        assert a.id == b.id
    claims: list[str] = []

    def claim(name: str) -> None:
        with client.factory() as db:
            if job_service.claim_next(db, name):
                claims.append(name)

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(claims) == 1


def test_recover_fails_orphaned_job_and_queues_resume(client):
    h = register_and_login(client, "rec@x.com")
    t = _task(client, h)
    tid = uuid.UUID(t["id"])
    with client.factory() as db:
        task = db.get(Task, tid)
        task.status = "GENERATING"  # mid-run when the worker died
        job = job_service.enqueue(db, tid, "start")
        job_service.claim_next(db, "dead-worker")
        db.query(Job).update({"claimed_at": run_service._now() - timedelta(hours=1)})
        db.commit()
        assert job_service.recover(db) == 1
        jobs = {j.id: j for j in db.query(Job).all()}
        assert jobs[job.id].status == "failed" and jobs[job.id].error == "worker lost"
        assert sorted(j.kind for j in jobs.values()) == ["resume", "start"]
        assert job_service.recover(db) == 0  # already queued: no duplicates


def test_recover_leaves_a_live_worker_alone(client):
    h = register_and_login(client, "live@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    with client.factory() as db:
        db.get(Task, tid).status = "GENERATING"
        job_service.enqueue(db, tid, "start")
        job_service.claim_next(db, "slow-worker")
        assert lease_service.acquire(db, tid, owner="slow-worker", ttl=60)
        db.query(Job).update({"claimed_at": run_service._now() - timedelta(hours=1)})
        db.commit()
        assert job_service.recover(db) == 0
        assert db.query(Job).one().status == "running"


def test_resume_job_with_nothing_to_resume_is_recorded(client):
    h = register_and_login(client, "n@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    with client.factory() as db:
        job_service.enqueue(db, tid, "resume")
    assert run_once(client.factory, client.llm, client.sandbox, worker="w") is True
    with client.factory() as db:
        job = db.query(Job).one()
        assert job.status == "done" and job.error == "nothing to resume"


# ---- trusted proxy ------------------------------------------------------------------------


def _req(xff: str | None, host: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


def test_forwarded_header_ignored_without_trusted_proxies(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 0)
    assert client_ip(_req("1.2.3.4")) == "10.0.0.9"


def test_forwarded_header_uses_nth_entry_from_the_right(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    # a client-forged leftmost entry must not win over what our proxy appended
    assert client_ip(_req("6.6.6.6, 203.0.113.7")) == "203.0.113.7"
    monkeypatch.setattr(settings, "trusted_proxy_count", 2)
    assert client_ip(_req("6.6.6.6, 203.0.113.7, 10.1.1.1")) == "203.0.113.7"


def test_missing_or_short_forwarded_chain_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 2)
    assert client_ip(_req(None)) == "10.0.0.9"
    assert client_ip(_req("1.2.3.4")) == "10.0.0.9"
