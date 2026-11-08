"""Phase 12 drills as tests: crash recovery, backup/restore, and the load/isolation check.

The chaos drill and the live-server load smoke are marked `slow` (they start real processes);
the gate runs them explicitly. The backup and load-test logic are also tested directly,
including that the
checks FAIL when they should, so a drill cannot pass by being blind.
"""

import importlib.util
import io
import os
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---- chaos drill -------------------------------------------------------------------------------


@pytest.mark.slow
def test_a_killed_worker_is_replaced_and_the_task_completes_from_its_checkpoint():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "chaos_drill.py"), "--timeout", "120"],
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
    assert "CHAOS DRILL: PASS" in r.stdout
    assert "Planner=1 Builder=1 Reviewer=1" in r.stdout  # completed work was not repeated
    assert "takeover logged" in r.stdout and "'start', 'failed', 'worker lost'" in r.stdout


# ---- backup / restore --------------------------------------------------------------------------


def test_backup_drill_restores_identical_data_and_refuses_corruption():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backup_drill.py")],
        capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
    assert "BACKUP DRILL: PASS" in r.stdout
    assert "corrupted backup refused" in r.stdout and "still append-only after restore" in r.stdout


def test_restore_refuses_archives_that_escape_the_target_directory(tmp_path):
    drill = _load("backup_drill")
    bad = tmp_path / "workspaces.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        payload = b"owned"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(drill.BackupError, match="unsafe path"):
        drill._safe_extract(bad, tmp_path / "dest")
    assert not (tmp_path / "evil.txt").exists()


def test_tree_digest_notices_any_change(tmp_path):
    drill = _load("backup_drill")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.py").write_text("x = 1\n")
    first = drill.tree_digest(tmp_path)
    (tmp_path / "a" / "f.py").write_text("x = 2\n")
    assert drill.tree_digest(tmp_path) != first
    (tmp_path / "a" / "g.py").write_text("")
    assert drill.tree_digest(tmp_path) != first


# ---- load test logic (the checks must be able to fail) -----------------------------------------


def _scripted_call(responses):
    """A fake `call` that returns canned (status, payload) by (method, path-prefix)."""

    def fake(rec, base, method, path, **kwargs):
        for (m, prefix), reply in responses.items():
            if method == m and path.startswith(prefix):
                status, payload = reply() if callable(reply) else reply
                rec.add(status, 0.001)
                if status not in kwargs.get("expect", (200,)):
                    rec.problem(f"{method} {path}: HTTP {status}")
                return status, payload
        raise AssertionError(f"unscripted call {method} {path}")

    return fake


def _run_one_user(load, monkeypatch, listing, task_status=201):
    monkeypatch.setattr(
        load,
        "call",
        _scripted_call(
            {
                ("POST", "/api/v1/auth/register"): (201, {}),
                ("POST", "/api/v1/auth/login"): (200, {"access_token": "t"}),
                ("POST", "/api/v1/projects"): (201, {"id": "p1"}),
                ("POST", "/api/v1/tasks"): (task_status, {"id": "t1"}),
                ("GET", "/api/v1/tasks/t1"): (200, {}),
                ("GET", "/api/v1/tasks"): listing,
            }
        ),
    )
    rec = load.Recorder()
    shared = {"lock": threading.Lock(), "tasks": {}}
    load.virtual_user(rec, "http://x", 0, 1, 2, shared, threading.Barrier(1))
    return rec


def test_load_check_passes_when_each_user_sees_exactly_their_own_tasks(monkeypatch):
    load = _load("load_test")
    rec = _run_one_user(load, monkeypatch, (200, [{"id": "t1"}]))
    assert rec.problems == [] and rec.statuses.get(500) is None


def test_load_check_flags_a_leaked_foreign_task(monkeypatch):
    load = _load("load_test")
    rec = _run_one_user(load, monkeypatch, (200, [{"id": "t1"}, {"id": "someone-elses"}]))
    assert any("leak or loss" in p for p in rec.problems)


def test_load_check_flags_lost_tasks_and_server_errors(monkeypatch):
    load = _load("load_test")
    assert any("leak or loss" in p for p in _run_one_user(load, monkeypatch, (200, [])).problems)
    rec = _run_one_user(load, monkeypatch, (500, None), task_status=500)
    assert rec.statuses.get(500, 0) >= 1 and rec.problems


# ---- load smoke against a real server ----------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.slow
def test_a_real_server_survives_concurrent_users_without_errors_or_leaks(tmp_path):
    load = _load("load_test")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "TEST_"))}
    env.update(
        DATABASE_URL=f"sqlite:///{tmp_path / 'load.db'}",
        WORKSPACE_ROOT=str(tmp_path / "ws"),
        ENVIRONMENT="development",
        LLM_PROVIDER="fake",
        SANDBOX_BACKEND="fake",
        PYTHONPATH=str(BACKEND),
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
        capture_output=True,
    )  # fmt: skip
    port = _free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)]
        + ["--log-level", "warning"],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=2)  # noqa: S310
                break
            except Exception:
                assert time.monotonic() < deadline and server.poll() is None, "server did not start"
                time.sleep(0.3)
        result = load.run(f"http://127.0.0.1:{port}", users=12, tasks=3, reads=6)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    print(result["latency_seconds"], result["requests_per_second"], "req/s")
    assert result["server_errors"] == 0, result
    assert result["problems"] == [], result["problems"]
    assert result["requests"] >= 12 * (3 + 4)
    assert set(result["statuses"]) <= {200, 201, 404}
