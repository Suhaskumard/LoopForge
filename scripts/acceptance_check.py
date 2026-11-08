"""Spec 15.1 acceptance checklist, each item tied to executable evidence.

    python scripts/acceptance_check.py            # SQLite, fake LLM, scripted sandbox
    DATABASE_URL=postgresql+psycopg://... python scripts/acceptance_check.py

Output per item: PASS (evidence shown), SKIP (cannot be established in this environment; the reason
says what to run), or FAIL. SKIP is NOT PASS: the final line counts them separately and the exit
code is non-zero only for FAIL. The model is a deterministic fake and the sandbox is scripted for the
loop scenarios, so items about *real* model quality or *real* container isolation are SKIP unless the
needed infrastructure is present.
"""

import ast
import json
import os
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="loopforge_accept_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{work / 'accept.db'}")
os.environ.update(
    {
        "WORKSPACE_ROOT": str(work / "workspaces"),
        "LLM_PROVIDER": "fake",
        "SANDBOX_BACKEND": "fake",
        "ENVIRONMENT": "development",
        "DOCUMENTATION_AGENT_ENABLED": "false",
    }
)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.api.dependencies import get_llm, get_sandbox  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.models import Base, Iteration  # noqa: E402
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
from app.execution.sandbox import build_run_args, docker_available  # noqa: E402
from app.main import app  # noqa: E402
from app.orchestrator.checkpoint import close_checkpointers  # noqa: E402
from app.schemas.plan import ProjectPlan  # noqa: E402
from app.services.llm_client import FakeLLMClient  # noqa: E402

Base.metadata.create_all(engine)
client = TestClient(app)
API = "/api/v1"
results: list[tuple[str, str, str]] = []  # (status, criterion, evidence)


def record(status: str, criterion: str, evidence: str) -> None:
    results.append((status, criterion, evidence))
    print(f"  [{status}] {criterion}\n         {evidence}")


def check(criterion: str, fn) -> None:
    try:
        status, evidence = fn()
    except Exception as exc:  # a crash in a check is a FAIL, never a silent pass
        status, evidence = "FAIL", f"{type(exc).__name__}: {exc}"
    record(status, criterion, evidence)


def scenario(script, llm_items, email, **task_extra):
    llm = FakeLLMClient().queue(*llm_items)
    sandbox = ScriptedSandbox(script)
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.post(f"{API}/auth/register", json={"email": email, "password": "accept12345"})
    tok = client.post(
        f"{API}/auth/login", data={"username": email, "password": "accept12345"}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    pid = client.post(f"{API}/projects", json={"name": "employee_management"}, headers=h).json()[
        "id"
    ]
    body = {"project_id": pid, "requirement": DEMO_REQUIREMENT, **task_extra}
    tid = client.post(f"{API}/tasks", json=body, headers=h).json()["id"]
    client.post(f"{API}/tasks/{tid}/start", headers=h)
    return h, tid, tok, llm, sandbox


def get(h, path):
    return client.get(f"{API}{path}", headers=h).json()


HAPPY = [demo_plan(), defective_builder_output(), repair_output(), review_output()]
print("== LoopForge spec 15.1 acceptance checklist ==")
h, tid, tok, llm, sandbox = scenario(
    [failing_update_report(), passing_report_for_demo()], HAPPY, "a1@example.com"
)
task = get(h, f"/tasks/{tid}")
its = get(h, f"/tasks/{tid}/iterations")
events = get(h, f"/tasks/{tid}/events")

check(
    "1. A user can create a project and submit a natural-language task",
    lambda: (
        "PASS",
        f"project + task created through the API; task {tid[:8]} status {task['status']}",
    )
    if task["requirement"] == DEMO_REQUIREMENT
    else ("FAIL", "task not stored"),
)


def c2():
    plan = ProjectPlan.model_validate(get(h, f"/tasks/{tid}/plan")["plan"])
    return (
        "PASS",
        f"{len(plan.requirements)} requirements, {len(plan.acceptance_criteria)} acceptance criteria, schema-valid",
    )


check("2. The Planner produces a structured, schema-validated plan", c2)


def c3():
    files = get(h, f"/tasks/{tid}/files")
    n = 0
    for f in files:
        if f["path"].endswith(".py"):
            ast.parse(get(h, f"/tasks/{tid}/files/{f['path']}")["content"])
            n += 1
    return (
        ("PASS", f"{n} Python files written and parsed with ast.parse")
        if n >= 3
        else ("FAIL", f"only {n} .py files")
    )


check("3. The Builder generates real Python files", c3)


def c4():
    import subprocess

    args = build_run_args("n", Path("/ws/src"), Path("/ws/out"), ["pytest"])
    controls = "--network" in args and "--read-only" in args and "--cap-drop" in args
    if not controls:
        return "FAIL", "isolation flags missing from the docker command"
    if not docker_available():
        return "SKIP", "docker command-line controls verified, but no Docker daemon is reachable"
    have = (
        subprocess.run(
            ["docker", "image", "inspect", settings.sandbox_image], capture_output=True
        ).returncode
        == 0
    )
    if not have:
        return (
            "SKIP",
            f"Docker is running but image '{settings.sandbox_image}' is not built: `docker build -t {settings.sandbox_image} backend/sandbox`, then re-run",
        )
    from app.demo.employee_management import builder_output
    from app.evaluation.test_runner import run_tests
    from app.execution.sandbox import DockerSandbox

    src, out = work / "docker_src", work / "docker_out"
    src.mkdir()
    out.mkdir()
    for fc in builder_output().files:
        p = src / fc.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(fc.content, encoding="utf-8")
    summary, _ = run_tests(DockerSandbox(), src, out, 180)
    if summary.report_found and summary.total > 0 and summary.failed == 0:
        return (
            "PASS",
            f"{summary.passed}/{summary.total} tests ran inside the locked-down container (no network, read-only, non-root, capped)",
        )
    return "FAIL", f"container run: {summary.passed}/{summary.total}, found={summary.report_found}"


check("4. Generated code executes in an isolated sandbox", c4)


def c5():
    sys.path.insert(0, str(ROOT / "benchmarks"))
    import shutil

    from host_sandbox import HostSandbox
    from app.demo.employee_management import builder_output
    from app.evaluation.test_runner import run_tests
    from app.services import workspace as ws

    src, out = work / "real_src", work / "real_out"
    src.mkdir()
    out.mkdir()
    for fc in builder_output().files:
        p = src / fc.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(fc.content, encoding="utf-8")
    summary, _ = run_tests(HostSandbox(), src, out, 120)
    shutil.rmtree(src, ignore_errors=True)
    _ = ws
    if summary.report_found and summary.total > 0 and summary.failed == 0:
        return (
            "PASS",
            f"real pytest on the demo project: {summary.passed}/{summary.total} passed, parsed from pytest's own JSON report (host process; isolation is item 4)",
        )
    return "FAIL", f"real pytest result {summary.passed}/{summary.total}"


check("5. The Verifier runs real Pytest tests", c5)


def c6():
    repair_prompt = next(c.user for c in llm.calls if c.response_model == "RepairOutput")
    return (
        ("PASS", "the failing test's report reached the Repair agent as its input")
        if "test_update" in repair_prompt or "404" in repair_prompt
        else ("FAIL", "failure details absent from the Repair prompt")
    )


check("6. Failures are captured and passed to the Repair Agent", c6)


def c7():
    d = get(h, f"/iterations/{its[1]['id']}/diff")
    changed = [f["path"] for f in d["files"]]
    return (
        ("PASS", f"Repair changed {changed} (iteration 2 vs 1)")
        if changed
        else ("FAIL", "no code change")
    )


check("7. The Repair Agent modifies the generated code", c7)


def c8():
    kinds = [e["event_type"] for e in events]
    after = kinds[kinds.index("repair_applied") :]
    return (
        (
            "PASS",
            f"after repair_applied: {after.count('tests_executed')} full test run(s) before acceptance; pytest ran {sandbox.pytest_runs}x",
        )
        if "tests_executed" in after and sandbox.pytest_runs == 2
        else ("FAIL", f"events after repair: {after}")
    )


check("8. Tests re-run automatically after every correction", c8)


def c9():
    h2, t2, _, _, _ = scenario(
        [failing_update_report()],
        [demo_plan(), defective_builder_output()],
        "a9@example.com",
        max_iterations=1,
    )
    s1 = get(h2, f"/tasks/{t2}")["status"]
    h3, t3, _, _, _ = scenario(
        FAIL_FOREVER,
        [demo_plan(), defective_builder_output(), *([repair_output()] * 4)],
        "a9b@example.com",
        token_budget=1000,
    )
    s2 = get(h3, f"/tasks/{t3}")["status"]
    return (
        (
            "PASS",
            f"iteration limit -> {s1}; token budget -> {s2}; (time/repeat limits: Decision Engine 100% branch coverage)",
        )
        if s1 == s2 == "ESCALATED"
        else ("FAIL", f"{s1}/{s2}")
    )


FAIL_FOREVER = [failing_update_report()]
check("9. The Decision Engine enforces retry and resource limits", c9)


def c10():
    runs = get(h, f"/tasks/{tid}/agent-runs")
    rv = [r for r in runs if r["agent_name"] == "Reviewer"]
    h4, t4, _, l4, _ = scenario(
        FAIL_FOREVER,
        [demo_plan(), defective_builder_output(), *([repair_output()] * 4)],
        "a10@example.com",
        max_iterations=1,
    )
    asked = any(c.response_model == "ReviewOutput" for c in l4.calls)
    return (
        (
            "PASS",
            f"Reviewer ran as its own agent ({len(rv)} run(s)) and is not consulted while tests fail (consulted={asked})",
        )
        if rv and not asked
        else ("FAIL", f"reviewer runs {len(rv)}, consulted on red={asked}")
    )


check("10. The Reviewer independently evaluates the implementation", c10)


def c11():
    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(Iteration))
    dialect = engine.dialect.name
    if dialect != "postgresql":
        return (
            "SKIP",
            f"{n} iteration rows persisted in {dialect}; re-run with DATABASE_URL=postgresql+psycopg://... (the Postgres gate does) to establish this item",
        )
    return "PASS", f"{n} iteration rows persisted in PostgreSQL"


check("11. Every iteration is stored in PostgreSQL", c11)


def c12():
    from starlette.websockets import WebSocketDisconnect

    got = []
    with client.websocket_connect(f"/ws/tasks/{tid}?token={tok}") as ws:
        while True:
            try:
                got.append(ws.receive_json()["event"])
            except WebSocketDisconnect:
                break
    need = {
        "task_started",
        "agent_started",
        "agent_completed",
        "tests_completed",
        "retry_scheduled",
        "task_completed",
    }
    if not need <= set(got):
        return "FAIL", f"missing events {need - set(got)}"
    if os.environ.get("ACCEPTANCE_UI_VERIFIED") != "1":
        return (
            "SKIP",
            f"the WebSocket delivered {len(got)} live events, but rendering in the dashboard needs a browser: follow docs/demo_runbook.md, then set ACCEPTANCE_UI_VERIFIED=1",
        )
    return "PASS", f"{len(got)} live events and the UI was verified manually"


check("12. The dashboard shows live workflow progress", c12)


def c13():
    a = get(h, f"/iterations/{its[1]['id']}/diff")
    b = client.get(
        f"{API}/iterations/{its[1]['id']}/diff", params={"against": its[0]["id"]}, headers=h
    ).json()
    return (
        (
            "PASS",
            f"diff available for the previous iteration and for any chosen one (against={b['against']}); API level",
        )
        if a["files"] and b["files"]
        else ("FAIL", "empty diff")
    )


check("13. Users can inspect code differences between iterations", c13)


def c14():
    r = get(h, f"/tasks/{tid}/report")
    md = client.get(f"{API}/tasks/{tid}/report.md", headers=h).text
    ok = (
        r["tests"]["total"] > 0
        and r["iterations"]
        and "Iteration history" in md
        and r["requirements"]
    )
    return (
        (
            "PASS",
            f"report: {r['tests']['passed']}/{r['tests']['total']} tests, {len(r['iterations'])} iterations, {len(r['requirements'])} traced requirements, markdown {len(md)} chars",
        )
        if ok
        else ("FAIL", "report incomplete")
    )


check("14. The system produces a final report with execution evidence", c14)


def c15():
    h5, t5, _, _, _ = scenario(
        FAIL_FOREVER,
        [demo_plan(), defective_builder_output(), *([repair_output()] * 4)],
        "a15@example.com",
        max_iterations=2,
    )
    st = get(h5, f"/tasks/{t5}")["status"]
    rep = get(h5, f"/tasks/{t5}/report")
    never = (
        st != "COMPLETED" and "NOT accepted" in rep["outcome"] and "Accepted" not in rep["outcome"]
    )
    return (
        ("PASS", f"a task whose tests never pass ends {st}, and its report says: {rep['outcome']}")
        if never
        else ("FAIL", f"{st}: {rep['outcome']}")
    )


check("15. A failed or unsafe task is escalated, never falsely marked successful", c15)

close_checkpointers()
counts = {s: sum(1 for r in results if r[0] == s) for s in ("PASS", "SKIP", "FAIL")}
print(
    f"\nSUMMARY: {counts['PASS']} PASS, {counts['SKIP']} SKIP (not established here), {counts['FAIL']} FAIL of {len(results)}"
)
(ROOT / "benchmarks" / "results").mkdir(parents=True, exist_ok=True)
(work / "acceptance.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
if counts["FAIL"]:
    print("ACCEPTANCE: FAIL")
    sys.exit(1)
print(
    "ACCEPTANCE: no failures"
    + (
        f"; {counts['SKIP']} item(s) still need infrastructure (see SKIP lines)"
        if counts["SKIP"]
        else ""
    )
)
