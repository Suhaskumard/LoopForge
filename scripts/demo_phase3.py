"""Phase 3 demo: sandboxed execution evidence.

Part A runs the full API flow with the deterministic FakeSandbox (no Docker needed).
Part B runs the real exit-gate checks inside Docker when a daemon and the image are available
(`docker build -t loopforge-sandbox backend/sandbox`); otherwise it says so and skips.

    python scripts/demo_phase3.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="loopforge_demo3_"))
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

from app.api.dependencies import get_sandbox  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.demo.employee_management import DEMO_REQUIREMENT  # noqa: E402
from app.evaluation.test_runner import run_tests  # noqa: E402
from app.execution.fake_sandbox import FakeSandbox, failing_report  # noqa: E402
from app.execution.sandbox import DockerSandbox, build_run_args, docker_available  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(engine)
client = TestClient(app)


def ok(label: str, cond: bool) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        sys.exit(1)


creds = {"email": "demo3@example.com", "password": "demo12345"}
client.post("/api/v1/auth/register", json=creds)
tok = client.post(
    "/api/v1/auth/login", data={"username": creds["email"], "password": creds["password"]}
).json()["access_token"]
h = {"Authorization": f"Bearer {tok}"}


def run_task(sandbox: FakeSandbox) -> str:
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    p = client.post("/api/v1/projects", json={"name": "employee_management"}, headers=h).json()
    t = client.post(
        "/api/v1/tasks", json={"project_id": p["id"], "requirement": DEMO_REQUIREMENT}, headers=h
    ).json()["id"]
    client.post(f"/api/v1/tasks/{t}/start", headers=h)
    return str(t)


print("=== A1. Generated project executed through the sandbox; evidence stored ===")
tid = run_task(FakeSandbox())
res = client.get(f"/api/v1/tasks/{tid}/iterations/1/test-results", headers=h).json()[0]
logs = client.get(f"/api/v1/tasks/{tid}/iterations/1/logs", headers=h).json()
print(f"   tests: {res['passed']} passed / {res['failed']} failed; logs: {[x['name'] for x in logs]}")
ok("test_results row stored", res["total_tests"] == 3)
ok("execution logs stored as artifacts", len(logs) == 2)
ok("task COMPLETED (green first run)", client.get(f"/api/v1/tasks/{tid}", headers=h).json()["status"] == "COMPLETED")

print("\n=== A2. Deliberately broken code -> captured failure with stack trace ===")
tid = run_task(FakeSandbox(failing_report()))
res = client.get(f"/api/v1/tasks/{tid}/iterations/1/test-results", headers=h).json()[0]
fail = res["details"]["failures"][0]
print(f"   {fail['nodeid']}: {fail['message']}")
ok("failure recorded with traceback", res["failed"] == 1 and "assert" in fail["traceback"])

print("\n=== A3. Section 13.1 controls on the docker command line ===")
cmd = " ".join(build_run_args("x", Path("/a"), Path("/b"), ["python", "-m", "pytest"]))
for flag in (
    "--network none",
    "--read-only",
    "--cap-drop ALL",
    "no-new-privileges",
    "--memory",
    "--cpus",
    "--pids-limit",
    "--user 10001",
):
    ok(flag, flag in cmd)
ok("no docker socket / privileged", "docker.sock" not in cmd and "--privileged" not in cmd)

print("\n=== B. Real containers ===")
image_ok = (
    docker_available()
    and subprocess.run(
        ["docker", "image", "inspect", "loopforge-sandbox"], capture_output=True
    ).returncode
    == 0
)
if not image_ok:
    print(
        "  [SKIP] Docker daemon or 'loopforge-sandbox' image not available; run "
        "`docker build -t loopforge-sandbox backend/sandbox` and re-run."
    )
else:

    def project(name: str, body: str) -> tuple[Path, Path]:
        src = work / name / "src"
        (src / "tests").mkdir(parents=True)
        (src / "tests" / "test_x.py").write_text(body, encoding="utf-8")
        return src, work / name / "out"

    src, out = project("broken", "def test_b():\n    assert {}['k']\n")
    s, _ = run_tests(DockerSandbox(), src, out, 60)
    ok("broken file: failure + stack trace", s.failed == 1 and "KeyError" in s.failures[0].traceback)
    src, out = project("loop", "def test_l():\n    while True:\n        pass\n")
    s, _ = run_tests(DockerSandbox(), src, out, 8)
    left = subprocess.run(
        ["docker", "ps", "-a", "-q", "--filter", "label=loopforge.sandbox=1"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    ok("runaway process killed at the time limit", s.timed_out)
    ok("container removed", left == "")

print("\nPHASE 3 DEMO: ALL CHECKS PASSED")
