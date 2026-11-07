"""Phase 2 demo: runs the spec §15.2 task through Planner -> Builder with the deterministic fake
LLM and prints the evidence for each exit-gate item. No API key, network or Docker needed.

    python scripts/demo_phase2.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="loopforge_demo_"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{work / 'demo.db'}",
        "WORKSPACE_ROOT": str(work / "workspaces"),
        "LLM_PROVIDER": "fake",
        "ENVIRONMENT": "development",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.dependencies import get_llm  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.demo.employee_management import DEMO_REQUIREMENT, demo_plan  # noqa: E402
from app.main import app  # noqa: E402
from app.services.llm_client import FakeLLMClient  # noqa: E402

Base.metadata.create_all(engine)
client = TestClient(app)


def hdr() -> dict[str, str]:
    creds = {"email": "demo@example.com", "password": "demo12345"}
    client.post("/api/v1/auth/register", json=creds)
    tok = client.post(
        "/api/v1/auth/login", data={"username": creds["email"], "password": creds["password"]}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def new_task(h: dict[str, str]) -> str:
    p = client.post("/api/v1/projects", json={"name": "employee_management"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks",
        json={"project_id": p["id"], "requirement": DEMO_REQUIREMENT},
        headers=h,
    )
    return str(t.json()["id"])


def ok(label: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        sys.exit(1)


h = hdr()
print("=== 1. Demo requirement -> schema-valid plan with requirement IDs + criteria ===")
tid = new_task(h)
r = client.post(f"/api/v1/tasks/{tid}/start", headers=h)  # `fake` provider serves the demo
plan = client.get(f"/api/v1/tasks/{tid}/plan", headers=h).json()["plan"]
reqs = client.get(f"/api/v1/tasks/{tid}/requirements", headers=h).json()
print(f"  requirement: {DEMO_REQUIREMENT}")
for q in reqs:
    print(f"   {q['req_id']}  {q['req_type']:<14} {q['priority']:<8} {q['description']}")
print("  acceptance criteria:", json.dumps(plan["acceptance_criteria"]))
ok("start accepted (202)", r.status_code == 202)
ok("plan has acceptance criteria", len(plan["acceptance_criteria"]) >= 1)
ok("requirements have IDs REQ-001..", [q["req_id"] for q in reqs][:2] == ["REQ-001", "REQ-002"])

print("\n=== 2. Builder wrote a complete project into the task workspace ONLY ===")
files = client.get(f"/api/v1/tasks/{tid}/files", headers=h).json()
root = Path(os.environ["WORKSPACE_ROOT"])
on_disk = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
for f in files:
    print(f"   {f['path']:<24} sha256:{f['sha256'][:12]}")
ok("every planned file was written", {f["path"] for f in files} == {f["path"] for f in plan["files"]})
ok(
    "all files live under <workspace>/<task>/iter_1/ and nowhere else",
    all(p.startswith(f"{tid}/") for p in on_disk)  # Phase 3 adds logs/ and out/ beside iter_1/
    and len([p for p in on_disk if p.startswith(f"{tid}/iter_1/")]) == len(files),
)

print("\n=== 3. Agent runs, tokens, lifecycle ===")
runs = client.get(f"/api/v1/tasks/{tid}/agent-runs", headers=h).json()
for a in runs:
    print(f"   {a['agent_name']:<8} {a['status']:<8} tokens={a['tokens_used']:<6} {a['duration_seconds']:.3f}s")
ok("token usage recorded in agent_runs", all(a["tokens_used"] > 0 for a in runs if a["agent_name"] != "Verifier"))
status = client.get(f"/api/v1/tasks/{tid}", headers=h).json()["status"]
ok(f"task advanced to TESTING by the Phase 3 executor (is {status})", status == "TESTING")

print("\n=== 4. Malformed LLM output is rejected and logged, never silently accepted ===")
bad = FakeLLMClient().queue("this is not JSON", {"project_name": "Bad Name!"})
app.dependency_overrides[get_llm] = lambda: bad
tid2 = new_task(h)
client.post(f"/api/v1/tasks/{tid2}/start", headers=h)
events = client.get(f"/api/v1/tasks/{tid2}/events", headers=h).json()
rejected = [e for e in events if e["event_type"] == "agent_output_rejected"]
for e in rejected:
    print(f"   rejected attempt {e['event_data']['attempt']}: {e['event_data']['reason'][:90]}")
ok("both malformed outputs were logged as rejected", len(rejected) == 2)
ok("task ended FAILED (not accepted)", client.get(f"/api/v1/tasks/{tid2}", headers=h).json()["status"] == "FAILED")
ok("no requirements/files were persisted", client.get(f"/api/v1/tasks/{tid2}/files", headers=h).json() == [])

print("\n=== 5. Prompt injection cannot escape the workspace ===")
from app.demo.employee_management import builder_output  # noqa: E402

out = builder_output().model_dump()
out["files"].append({"path": "../../evil.py", "content": "import os", "action": "create"})
app.dependency_overrides[get_llm] = lambda: FakeLLMClient().queue(demo_plan(), out, out)
tid3 = new_task(h)
client.post(f"/api/v1/tasks/{tid3}/start", headers=h)
ok("escaping path refused, task FAILED", client.get(f"/api/v1/tasks/{tid3}", headers=h).json()["status"] == "FAILED")
ok("nothing named evil.py exists anywhere", not list(work.rglob("evil.py")))
print("\nPHASE 2 DEMO: ALL CHECKS PASSED")
