"""Phase 3: sandboxed execution evidence through the public API (FakeSandbox, no Docker)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_sandbox
from app.database.models import Artifact, TestResult
from app.demo.employee_management import demo_responses
from app.execution.fake_sandbox import FakeSandbox, failing_report
from app.execution.sandbox import SandboxError
from app.main import app
from tests.conftest import register_and_login
from tests.integration.test_phase2_flow import _events, _setup, _start, _task


def _run(client, sandbox=None, email="p3@x.com"):
    if sandbox is not None:
        app.dependency_overrides[get_sandbox] = lambda: sandbox
    h, t = _setup(client, email)
    client.llm.queue(*demo_responses())
    _start(client, h, t["id"])
    return h, t["id"]


def _results(client, h, tid):
    return client.get(f"/api/v1/tasks/{tid}/iterations/1/test-results", headers=h).json()


def test_passing_run_stores_real_results_and_logs(client):
    h, tid = _run(client)
    assert _task(client, h, tid)["status"] == "TESTING"
    (res,) = _results(client, h, tid)
    assert (res["total_tests"], res["passed"], res["failed"]) == (3, 3, 0)
    logs = client.get(f"/api/v1/tasks/{tid}/iterations/1/logs", headers=h).json()
    assert [entry["name"] for entry in logs] == ["pytest-stderr.txt", "pytest-stdout.txt"]
    assert "fake run" in logs[1]["content"] and len(logs[1]["sha256"]) == 64
    with Session(client.engine) as s:
        kinds = {a.artifact_type for a in s.scalars(select(Artifact))}
    assert kinds == {"source", "log"}
    ev = _events(client, h, tid)
    assert ev[-1]["event_type"] == "tests_executed" and ev[-1]["event_data"]["passed"] == 3


def test_executes_only_allowlisted_command_on_the_iteration_directory(client):
    seen = {}
    sb = FakeSandbox(hook=lambda ws, argv: seen.update(ws=ws, argv=argv))
    h, tid = _run(client, sb)
    assert seen["argv"][:3] == ["python", "-m", "pytest"]
    assert seen["ws"].name == "iter_1" and seen["ws"].parent.name == tid
    assert (seen["ws"] / "app" / "routes.py").is_file()


def test_broken_code_yields_captured_failure_with_stack_trace(client):
    h, tid = _run(client, FakeSandbox(failing_report()))
    (res,) = _results(client, h, tid)
    assert res["failed"] == 1 and res["passed"] == 1
    failure = res["details"]["failures"][0]
    assert failure["nodeid"].endswith("test_boom") and "assert 1 == 2" in failure["traceback"]
    assert _task(client, h, tid)["status"] == "TESTING"  # failures are evidence, not crashes


def test_runaway_process_reported_as_timeout(client):
    h, tid = _run(client, FakeSandbox(timed_out=True, stderr="killed"))
    (res,) = _results(client, h, tid)
    assert res["details"]["timed_out"] is True and res["failed"] == 1
    assert "exceeded" in res["details"]["failures"][0]["message"]


def test_missing_report_is_never_treated_as_success(client):
    sb = FakeSandbox(report=None, exit_code=1, stderr="SyntaxError: invalid syntax")
    sb.report = None
    h, tid = _run(client, sb)
    (res,) = _results(client, h, tid)
    assert res["failed"] == 1 and "SyntaxError" in res["details"]["failures"][0]["traceback"]


def test_sandbox_infrastructure_failure_fails_the_task(client):
    class Down:
        def run(self, *a, **k):
            raise SandboxError("docker daemon unavailable")

    h, tid = _run(client, Down())
    assert _task(client, h, tid)["status"] == "FAILED"
    ev = _events(client, h, tid)
    assert ev[-1]["event_type"] == "run_failed" and "sandbox" in ev[-1]["event_data"]["reason"]
    runs = client.get(f"/api/v1/tasks/{tid}/agent-runs", headers=h).json()
    assert runs[-1]["agent_name"] == "Verifier" and runs[-1]["status"] == "failed"
    with Session(client.engine) as s:
        assert s.scalars(select(TestResult)).first() is None  # nothing invented


def test_logs_and_results_are_owner_scoped(client):
    h, tid = _run(client)
    other = register_and_login(client, "intruder@x.com")
    for path in ("logs", "test-results"):
        r = client.get(f"/api/v1/tasks/{tid}/iterations/1/{path}", headers=other)
        assert r.status_code == 404
    assert client.get(f"/api/v1/tasks/{tid}/iterations/9/logs", headers=h).status_code == 404
    assert client.get(f"/api/v1/tasks/{tid}/iterations/1/logs").status_code == 401


@pytest.mark.parametrize("name", ["../x.txt", "a/../../b.txt"])
def test_log_names_cannot_escape(client, name):
    from app.database.models import Iteration
    from app.services import workspace
    from app.services.workspace import WorkspaceError

    _run(client)
    with Session(client.engine) as s:
        it = s.scalars(select(Iteration)).first()
        with pytest.raises(WorkspaceError):
            workspace.write_log(
                s, task_id=it.task_id, iteration_id=it.id, iteration_number=1,
                name=name, content="x",
            )  # fmt: skip
