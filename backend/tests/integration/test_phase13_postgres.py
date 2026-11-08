# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: behaviour that only a REAL PostgreSQL can prove.

Everything here is skipped unless TEST_DATABASE_URL points at PostgreSQL; `scripts/test_postgres.sh` starts a
throwaway server and runs this file (a skip is a failure there). Each test that needs its own schema creates a
fresh database, so nothing depends on test order or on the shared test database.
"""

import threading
import time
import uuid
from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database.migration_lock import MIGRATION_LOCK_KEY, migration_lock
from app.database.models import Base, Iteration, Job, Organization, Task
from tests.conftest import TEST_DATABASE_URL
from tests.integration.test_migrations import _cfg

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not (TEST_DATABASE_URL or "").startswith("postgresql"), reason="needs a real PostgreSQL"
    ),
]


# ---- helpers -----------------------------------------------------------------------------------------


def _admin_engine():
    url = make_url(TEST_DATABASE_URL).set(database="postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture
def fresh_db():
    """A brand-new empty database; dropped afterwards."""
    name = f"lf_{uuid.uuid4().hex[:12]}"
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_cfg(url), revision)


# ---- real Alembic ------------------------------------------------------------------------------------


def test_alembic_upgrade_produces_exactly_the_schema_the_models_describe(fresh_db):
    _upgrade(fresh_db)
    engine = create_engine(fresh_db)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"models drifted from the migrations on PostgreSQL: {diff}"


def test_alembic_downgrade_to_base_is_clean_and_upgrade_works_again(fresh_db):
    _upgrade(fresh_db)
    command.downgrade(_cfg(fresh_db), "base")
    engine = create_engine(fresh_db)
    with engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        }
        functions = {
            r[0]
            for r in conn.execute(
                text("SELECT proname FROM pg_proc WHERE proname='audit_log_immutable'")
            )
        }
    engine.dispose()
    assert tables == {"alembic_version"} and functions == set()  # incl. the trigger function
    _upgrade(fresh_db)  # and the schema can be rebuilt


def test_migration_0006_moves_existing_users_and_projects_into_personal_orgs(fresh_db):
    _upgrade(fresh_db, "0005")
    engine = create_engine(fresh_db)
    user_id, project_id, now = uuid.uuid4(), uuid.uuid4(), datetime(2026, 1, 1)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, token_version, created_at) "
                "VALUES (:id, 'legacy@example.com', 'x', 0, :now)"
            ),
            {"id": user_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, user_id, name, description, language, version, created_at) "
                "VALUES (:id, :uid, 'legacy', '', 'python', 1, :now)"
            ),
            {"id": project_id, "uid": user_id, "now": now},
        )
    _upgrade(fresh_db)
    with engine.connect() as conn:
        role, slug, same = conn.execute(
            text(
                "SELECT m.role, o.slug, p.org_id = o.id FROM memberships m "
                "JOIN organizations o ON o.id = m.org_id JOIN projects p ON p.id = :pid "
                "WHERE m.user_id = :uid"
            ),
            {"pid": project_id, "uid": user_id},
        ).one()
    engine.dispose()
    assert role == "admin" and slug.startswith("u-") and same is True


# ---- the append-only audit log -----------------------------------------------------------------------


def _insert_audit_row(conn) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_log (id, action, target_type, target_id, detail, ip, created_at) "
            "VALUES (:id, 'probe', '', '', CAST('{}' AS JSONB), '', now())"
        ),
        {"id": uuid.uuid4()},
    )


@pytest.mark.parametrize("builder", ["alembic", "create_all"])
def test_the_database_itself_refuses_to_change_or_delete_audit_rows(fresh_db, builder):
    """Both ways of building the schema (migration 0006 and the model DDL) install the trigger."""
    if builder == "alembic":
        _upgrade(fresh_db)
    else:
        engine = create_engine(fresh_db)
        Base.metadata.create_all(engine)
        engine.dispose()
    engine = create_engine(fresh_db)
    with engine.begin() as conn:
        _insert_audit_row(conn)
    for statement in (
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as conn:
                conn.execute(text(statement))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT action FROM audit_log")).scalar() == "probe"  # untouched
    engine.dispose()


# ---- advisory lock for migrations --------------------------------------------------------------------


def test_a_second_migration_runner_waits_for_the_first_and_then_proceeds(fresh_db):
    engine = create_engine(fresh_db)
    events: list[str] = []
    entered_second = threading.Event()

    def second_runner() -> None:
        with engine.connect() as conn, migration_lock(conn):
            events.append("second-in")
            entered_second.set()

    with engine.connect() as first:
        with migration_lock(first):
            events.append("first-in")
            t = threading.Thread(target=second_runner)
            t.start()
            time.sleep(1.0)  # plenty of time for the second to run IF the lock did not work
            assert (
                not entered_second.is_set()
            ), "the second runner got in while the first held the lock"
            events.append("first-done")
        t.join(timeout=15)
    assert entered_second.is_set() and events == ["first-in", "first-done", "second-in"]
    engine.dispose()


def test_the_lock_is_released_when_a_migration_fails(fresh_db):
    engine = create_engine(fresh_db)
    with engine.connect() as conn:
        with pytest.raises(RuntimeError):
            with migration_lock(conn):
                raise RuntimeError("bad migration")
    with engine.connect() as other:  # a different connection can take it straight away
        got = other.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY}
        ).scalar()
        assert got is True
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
    engine.dispose()


def test_real_alembic_runs_are_serialised_by_the_lock(fresh_db):
    """Three replicas running `alembic upgrade head` at the same moment on an empty database all succeed.

    Separate PROCESSES, as in a real rolling deploy (Alembic's environment is not thread-safe, and two
    threads of one process are not what the lock protects against).
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    env = {**os.environ, "DATABASE_URL": fresh_db, "PYTHONPATH": str(backend)}
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for _ in range(3)
    ]  # fmt: skip
    outputs = [(p.wait(timeout=180), p.stdout.read()) for p in procs]
    failures = [out[-600:] for code, out in outputs if code != 0]
    assert failures == [], failures
    engine = create_engine(fresh_db)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0009"
    engine.dispose()


# ---- row locks, JSONB, leases, checkpoints (on the shared test database via the `client` fixture) -----


def test_select_for_update_makes_a_second_transition_wait(client):
    from tests.conftest import register_and_login

    h = register_and_login(client, "lock@x.com")
    p = client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": "Build a small API with tests please."},
        headers=h,
    ).json()
    task_id = uuid.UUID(t["id"])
    order: list[str] = []
    with client.factory() as a:
        a_task = a.execute(
            text("SELECT id FROM tasks WHERE id = :i FOR UPDATE"), {"i": task_id}
        ).first()
        assert a_task is not None

        def second() -> None:
            with client.factory() as b:
                b.execute(
                    text("SELECT id FROM tasks WHERE id = :i FOR UPDATE"), {"i": task_id}
                ).first()
                order.append("second-got-lock")
                b.commit()

        th = threading.Thread(target=second)
        th.start()
        time.sleep(1.0)
        assert order == [], "a second FOR UPDATE got through while the first transaction was open"
        order.append("first-commits")
        a.commit()
    th.join(timeout=15)
    assert order == ["first-commits", "second-got-lock"]


def test_jsonb_columns_are_real_jsonb_and_round_trip_nested_data(client):
    from tests.conftest import register_and_login

    h = register_and_login(client, "json@x.com")
    p = client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": "Build a small API with tests please."},
        headers=h,
    ).json()
    payload = {"decision": {"action": "retry", "n": [1, 2, {"deep": "ü"}]}, "tests": {"failed": 1}}
    with client.factory() as db:
        it = Iteration(task_id=uuid.UUID(t["id"]), iteration_number=1, feedback=payload)
        db.add(it)
        db.commit()
        it_id = it.id
    with client.factory() as db:
        assert db.get(Iteration, it_id).feedback == payload
        kind = db.execute(
            text(
                "SELECT data_type FROM information_schema.columns WHERE table_name='iterations' AND column_name='feedback'"
            )
        ).scalar()
        assert kind == "jsonb"  # not json/text: JSONB operators work
        assert (
            db.execute(
                text("SELECT feedback->'decision'->>'action' FROM iterations WHERE id = :i"),
                {"i": it_id},
            ).scalar()
            == "retry"
        )


def test_a_run_lease_is_taken_over_after_expiry_on_postgres(client):
    from app.services import lease_service
    from tests.conftest import register_and_login

    h = register_and_login(client, "lease@x.com")
    p = client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": "Build a small API with tests please."},
        headers=h,
    ).json()
    tid = uuid.UUID(t["id"])
    with client.factory() as db:
        assert lease_service.acquire(db, tid, owner="A", ttl=0.2)
        assert not lease_service.acquire(db, tid, owner="B")  # A is alive
        time.sleep(0.5)
        assert lease_service.acquire(db, tid, owner="B")  # A stopped renewing: taken over


def test_job_claims_are_exclusive_across_connections_on_postgres(client):
    from app.services import job_service
    from tests.conftest import register_and_login

    h = register_and_login(client, "claim@x.com")
    p = client.post("/api/v1/projects", json={"name": "p"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": "Build a small API with tests please."},
        headers=h,
    ).json()
    with client.factory() as db:
        job_service.enqueue(db, uuid.UUID(t["id"]), "start")
    winners: list[str] = []

    def claim(name: str) -> None:
        with client.factory() as db:
            if job_service.claim_next(db, name):
                winners.append(name)

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(8)]
    [x.start() for x in threads]
    [x.join() for x in threads]
    assert len(winners) == 1
    with client.factory() as db:
        assert db.query(Job).filter_by(status="running").count() == 1


def test_the_postgres_checkpointer_stores_the_loop_state_and_a_run_completes(client):
    """The whole fake-LLM loop on PostgreSQL, with LangGraph's PostgresSaver as the checkpoint store."""
    from app.api.dependencies import get_sandbox
    from app.execution.fake_sandbox import ScriptedSandbox
    from app.main import app
    from tests.integration.test_phase4_loop import (
        HAPPY_LLM,
        failing_update_report,
        new_task,
        passing_report_for_demo,
    )

    app.dependency_overrides[get_sandbox] = lambda: ScriptedSandbox(
        [failing_update_report(), passing_report_for_demo()]
    )
    client.llm.queue(*HAPPY_LLM)
    h, tid = new_task(client, "ckpt@x.com")
    assert client.post(f"/api/v1/tasks/{tid}/start", headers=h).status_code == 202
    assert client.get(f"/api/v1/tasks/{tid}", headers=h).json()["status"] == "COMPLETED"
    with client.factory() as db:
        n = db.execute(text("SELECT count(*) FROM checkpoints")).scalar()
        assert n and n > 0, "no checkpoints were written to PostgreSQL"
        assert db.query(Organization).count() >= 1 and db.query(Task).count() >= 1


def test_naive_utc_timestamps_survive_a_round_trip_unchanged(client):
    from tests.conftest import register_and_login

    register_and_login(client, "ts@x.com")
    with client.factory() as db:
        before = datetime.utcnow().replace(microsecond=0)
        got = db.execute(text("SELECT created_at FROM users WHERE email = 'ts@x.com'")).scalar()
        assert isinstance(got, datetime) and got.tzinfo is None
        assert abs(got - before) < timedelta(minutes=5)
        assert isinstance(db, Session)
