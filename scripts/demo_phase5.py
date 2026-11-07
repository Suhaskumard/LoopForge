"""Phase 5 demo: evidence for the three exit-gate items (no API key, no Docker, no browser).

    python scripts/demo_phase5.py
"""

import os
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="loopforge_demo5_"))
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
from sqlalchemy import text  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.api.dependencies import get_llm, get_sandbox  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
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
from app.orchestrator.checkpoint import close_checkpointers  # noqa: E402
from app.services.llm_client import FakeLLMClient  # noqa: E402

Base.metadata.create_all(engine)
llm = FakeLLMClient().queue(
    demo_plan(), defective_builder_output(), repair_output(), review_output()
)
sandbox = ScriptedSandbox([failing_update_report(), passing_report_for_demo()])
app.dependency_overrides[get_llm] = lambda: llm
app.dependency_overrides[get_sandbox] = lambda: sandbox
client = TestClient(app)
API = "/api/v1"


def ok(label: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        sys.exit(1)


client.post(f"{API}/auth/register", json={"email": "demo5@example.com", "password": "demo12345"})
tok = client.post(
    f"{API}/auth/login", data={"username": "demo5@example.com", "password": "demo12345"}
).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}
pid = client.post(f"{API}/projects", json={"name": "employee_management"}, headers=h).json()["id"]
tid = client.post(
    f"{API}/tasks", json={"project_id": pid, "requirement": DEMO_REQUIREMENT}, headers=h
).json()["id"]
client.post(f"{API}/tasks/{tid}/start", headers=h)

print("== 1. Submit the demo task and watch every agent step (WebSocket /ws/tasks/{id}) ==")
events = []
with client.websocket_connect(f"/ws/tasks/{tid}?token={tok}") as ws:
    while True:
        try:
            events.append(ws.receive_json())
        except WebSocketDisconnect:
            break
for e in events:
    detail = e.get("agent") or e.get("status") or ""
    print(f"    {e['event']:<20} it.{e.get('iteration', '-')!s:<4} {detail}")
started = [e["agent"] for e in events if e["event"] == "agent_started"]
ok("every agent started AND finished", sorted(started) == sorted(
    e["agent"] for e in events if e["event"] == "agent_completed"))
ok("agents seen: " + ", ".join(dict.fromkeys(started)),
   {"Planner", "Builder", "Verifier", "Reviewer", "Repair"} <= set(started))
ok("sandbox, tests, repair and verdict events present", {
    "sandbox_started", "tests_completed", "retry_scheduled", "iteration_completed",
} <= {e["event"] for e in events})
ok("stream ends with task_completed", events[-1]["event"] == "task_completed")

print("== 2. Code differences between any two iterations ==")
its = client.get(f"{API}/tasks/{tid}/iterations", headers=h).json()
v1, v2 = its[0]["id"], its[1]["id"]
fwd = client.get(f"{API}/iterations/{v2}/diff", params={"against": v1}, headers=h).json()
back = client.get(f"{API}/iterations/{v1}/diff", params={"against": v2}, headers=h).json()
for f in fwd["files"]:
    print(f"    v2 vs v1: {f['path']} ({f['status']})")
    for line in f["diff"].splitlines():
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            print("      " + line)
ok("v2 vs v1 shows the repaired line", any("employee_id + 1" in f["diff"] for f in fwd["files"]))
ok("v1 vs v2 (reverse) is the mirror image", [f["path"] for f in back["files"]] == [f["path"] for f in fwd["files"]])

print("== 3. KPIs match figures computed directly from the database ==")
o = client.get(f"{API}/analytics/overview", headers=h).json()
with engine.connect() as c:
    done = c.execute(text("SELECT COUNT(*) FROM tasks WHERE status='COMPLETED'")).scalar()
    eligible = c.execute(text(
        "SELECT COUNT(*) FROM tasks WHERE status IN ('COMPLETED','FAILED','ESCALATED')")).scalar()
    iters = c.execute(text("SELECT COUNT(*) FROM iterations")).scalar()
    # one test_results row per iteration here; every executed test counts, failing run included
    passed = c.execute(text("SELECT SUM(passed) FROM test_results")).scalar()
    total = c.execute(text("SELECT SUM(total_tests) FROM test_results")).scalar()
    tokens = c.execute(text("SELECT SUM(tokens_used) FROM agent_runs")).scalar()
print(f"    {'KPI':<22}{'dashboard API':>16}{'SQL directly':>16}")
rows = [
    ("task success rate %", o["task_success_rate"], round(done * 100 / eligible, 2)),
    ("average iterations", o["average_iterations"], round(iters / done, 3)),
    ("test pass rate %", o["test_pass_rate"], round(passed * 100 / total, 2)),
    ("total tokens", o["total_tokens"], tokens),
    ("est. cost $", o["total_cost"], round(tokens / 1000 * settings.cost_per_1k_tokens, 6)),
]
for name, api_v, sql_v in rows:
    print(f"    {name:<22}{api_v!s:>16}{sql_v!s:>16}")
    ok(name, api_v == sql_v)

close_checkpointers()
print("ALL CHECKS PASSED")
