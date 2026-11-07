"""Phase 4 demo (Milestone 1): evidence for the five exit-gate items of the feedback loop.

Uses the deterministic FakeLLMClient and a ScriptedSandbox, so it needs no API key and no Docker.
(Real-container behaviour is covered by demo_phase3.py / `pytest -m docker`.)

    python scripts/demo_phase4.py
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="loopforge_demo4_"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{work / 'demo.db'}",
        "WORKSPACE_ROOT": str(work / "workspaces"),
        "LLM_PROVIDER": "fake",
        "SANDBOX_BACKEND": "fake",
        "ENVIRONMENT": "development",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.dependencies import get_llm, get_sandbox  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.models import Base, Task  # noqa: E402
from app.database.session import SessionLocal, engine  # noqa: E402
from app.demo.employee_management import (  # noqa: E402
    DEMO_REQUIREMENT,
    defective_builder_output,
    demo_plan,
    failing_update_report,
    passing_report_for_demo,
    repair_output,
    review_output,
)
from app.execution.fake_sandbox import ScriptedSandbox  # noqa: E402
from app.main import app  # noqa: E402
from app.services import run_service  # noqa: E402
from app.services.llm_client import FakeLLMClient  # noqa: E402

Base.metadata.create_all(engine)
client = TestClient(app)


class Crash(BaseException):
    """Stands in for the process dying mid-iteration."""


def ok(label: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        sys.exit(1)


creds = {"email": "demo4@example.com", "password": "demo12345"}
client.post("/api/v1/auth/register", json=creds)
tok = client.post(
    "/api/v1/auth/login", data={"username": creds["email"], "password": creds["password"]}
).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
project = client.post("/api/v1/projects", json={"name": "employee_management"}, headers=h).json()
PLAN, DEFECT = demo_plan(), defective_builder_output()


def failing(name: str) -> dict:
    r = failing_update_report()
    r["tests"][1]["nodeid"] = f"tests/test_routes.py::{name}"
    return r


def make_task(**kw: object) -> str:
    body = {"project_id": project["id"], "requirement": DEMO_REQUIREMENT, **kw}
    return str(client.post("/api/v1/tasks", json=body, headers=h).json()["id"])


def start(script: list, llm_items: list, **kw: object) -> tuple[str, ScriptedSandbox, FakeLLMClient]:
    sandbox, llm = ScriptedSandbox(script), FakeLLMClient().queue(*llm_items)
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    app.dependency_overrides[get_llm] = lambda: llm
    tid = make_task(**kw)
    client.post(f"/api/v1/tasks/{tid}/start", headers=h)
    return tid, sandbox, llm


def status(tid: str) -> str:
    return str(client.get(f"/api/v1/tasks/{tid}", headers=h).json()["status"])


def its(tid: str) -> list[dict]:
    return client.get(f"/api/v1/tasks/{tid}/iterations", headers=h).json()


print("=== 1. Injected defect fails, is repaired, and passes - no human input ===")
tid, sandbox, llm = start(
    [failing_update_report(), passing_report_for_demo()],
    [PLAN, DEFECT, repair_output(), review_output()],
)
for i in its(tid):
    t = i["tests"]
    print(f"   v{i['number']}: {t['passed']} passed / {t['failed']} failed -> {i['status']}")
rep = its(tid)[1]["repair"]
print(f"   root cause: {rep['root_cause']}")
diff = client.get(f"/api/v1/iterations/{its(tid)[1]['id']}/diff", headers=h).json()
print("   diff:", [f["path"] for f in diff["files"]])
ok("iteration 1 failed, iteration 2 accepted", [i["status"] for i in its(tid)] == ["failed_tests", "accepted"])
ok("task COMPLETED autonomously", status(tid) == "COMPLETED")

print("\n=== 2. Every repair is followed by a full test re-run before acceptance ===")
ev = client.get(f"/api/v1/tasks/{tid}/events", headers=h).json()
types = [e["event_type"] for e in ev]
after_repair = types[types.index("repair_applied") :]
print("   events after repair:", [t for t in after_repair if t != "status_changed"])
ok("pytest ran once per iteration, on that iteration's own workspace",
   [w.name for w in sandbox.workspaces] == ["iter_1", "iter_2"])
ok("tests_executed (iteration 2) happens between the repair and the acceptance",
   after_repair.index("tests_executed") < after_repair.index("decision"))

print("\n=== 3. The loop stops and escalates at the iteration, time and token limit ===")
tid, sb, _ = start(
    [failing("test_a"), failing("test_b"), failing("test_c")],
    [PLAN, DEFECT, repair_output()],
    max_iterations=2,
)
ok(f"iteration limit: ESCALATED after {len(its(tid))} iterations", status(tid) == "ESCALATED" and sb.pytest_runs == 2)
settings.max_task_duration_seconds = 0
tid, sb, _ = start([failing_update_report()], [PLAN, DEFECT])
ok("time limit: ESCALATED without starting another iteration", status(tid) == "ESCALATED" and sb.pytest_runs == 1)
settings.max_task_duration_seconds = 900
settings.max_token_budget = 4500
tid, sb, _ = start(
    [failing_update_report(), passing_report_for_demo()],
    [PLAN, DEFECT, repair_output(), review_output()],
)
ok("token limit: ESCALATED when the budget is spent", status(tid) == "ESCALATED")
settings.max_token_budget = 30000

print("\n=== 4. Identical repeated failures trigger escalation ===")
tid, sb, _ = start(
    [failing_update_report()], [PLAN, DEFECT, repair_output(), repair_output()]
)
fps = {i["decision"]["fingerprint"][:10] for i in its(tid)}
print(f"   {len(its(tid))} iterations, distinct failure fingerprints: {sorted(fps)}")
ok("same failure 3x -> ESCALATED well before the 5-iteration limit",
   status(tid) == "ESCALATED" and len(its(tid)) == 3 and len(fps) == 1)

print("\n=== 5. A workflow interrupted mid-iteration resumes from its checkpoint ===")
sandbox = ScriptedSandbox([failing_update_report(), Crash, passing_report_for_demo()])
llm = FakeLLMClient().queue(PLAN, DEFECT, repair_output(), review_output())
tid = make_task()
with SessionLocal() as db:
    run_service.prepare_start(db, db.get(Task, uuid.UUID(tid)))
try:
    run_service.execute_run(SessionLocal, uuid.UUID(tid), llm, sandbox)
except Crash:
    print(f"   process 'died' during iteration 2; task is stranded in {status(tid)}")
calls_before = len(llm.calls)
resumed = run_service.resume_run(SessionLocal, uuid.UUID(tid), llm, sandbox)
new_calls = [c.response_model for c in llm.calls[calls_before:]]
print(f"   resumed; LLM calls after resume: {new_calls}")
ok("resumed from the checkpoint and finished COMPLETED", resumed and status(tid) == "COMPLETED")
ok("planner/builder/repair were not repeated", new_calls == ["ReviewOutput"])

print("\nPHASE 4 DEMO: ALL CHECKS PASSED")
