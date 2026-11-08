"""Phase 8 gate: an existing repository is imported, patched and verified, all offline."""

import io
import uuid
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditEvent, Task, TestResult
from app.execution.fake_sandbox import (
    ScriptedSandbox,
    failing_report,
    jest_failing_report,
    jest_passing_report,
    passing_report,
)
from app.schemas.loop import (
    CriterionAssessment,
    RepairOutput,
    RequirementCoverage,
    ReviewOutput,
)
from app.schemas.plan import FileChange
from app.services import repo_import, run_service, workspace
from tests.conftest import register_and_login

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TESTS = (
    "from app.calc import add\n\n"
    "def test_add():\n    assert add(1, 2) == 3\n\n"
    "def test_add_zero():\n    assert add(0, 0) == 0\n"
)
CRITERIA = ["add(1, 2) returns 3"]
SEED = {"app/calc.py": BUGGY, "tests/test_calc.py": TESTS, "README.md": "# calc\n"}
REQ = [{"req_id": "REQ-001", "description": "add must add", "type": "functional"}]


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def planned(path, action="modify", purpose="change"):
    return {"path": path, "purpose": purpose, "implements": ["REQ-001"], "action": action}


def plan(files=None, base="existing"):
    return {
        "project_name": "calc",
        "framework": "FastAPI",
        "base": base,
        "requirements": REQ,
        "acceptance_criteria": CRITERIA,
        "files": files or [planned("app/calc.py", purpose="fix the addition")],
        "dependencies": [],
    }


def patch(content=FIXED, path="app/calc.py"):
    return {"files": [{"path": path, "content": content, "action": "modify"}]}


def review():
    return ReviewOutput(
        critical_issues=[],
        acceptance_criteria=[
            CriterionAssessment(criterion=c, met=True, evidence="tests") for c in CRITERIA
        ],
        requirement_coverage=[RequirementCoverage(req_id="REQ-001", covered=True)],
        maintainability_notes=[],
        quality_score=0.9,
    )


def fix_repair(path="app/calc.py", content=FIXED):
    return RepairOutput(
        root_cause="wrong operator",
        explanation="use the right operator",
        changes=[FileChange(path=path, content=content, action="modify")],
    )


def setup_task(client, *, language="python", source_type="zip", email="r@x.com", **extra):
    h = register_and_login(client, email)
    p = client.post(
        "/api/v1/projects", json={"name": "calc", "language": language}, headers=h
    ).json()
    body = {
        "project_id": p["id"],
        "requirement": "Fix add(): it subtracts.",
        "source_type": source_type,
        **extra,
    }
    t = client.post("/api/v1/tasks", json=body, headers=h)
    assert t.status_code == 201, t.text
    return h, t.json()


def upload(client, h, tid, files=None, name="repo.zip"):
    blob = make_zip(SEED if files is None else files)
    return client.post(
        f"/api/v1/tasks/{tid}/source",
        files={"file": (name, blob, "application/zip")},
        headers=h,
    )


def run_loop(client, tid, sandbox):
    with Session(client.engine) as s:
        run_service.prepare_start(s, s.get(Task, uuid.UUID(tid)))
    run_service.execute_run(client.factory, uuid.UUID(tid), client.llm, sandbox)
    with Session(client.engine) as s:
        return s.get(Task, uuid.UUID(tid)).status


def events(client, h, tid, kind):
    ev = client.get(f"/api/v1/tasks/{tid}/events", headers=h).json()
    return [e["event_data"] for e in ev if e["event_type"] == kind]


# ---- API surface -------------------------------------------------------------------------


def test_zip_task_cannot_start_before_upload_then_can(client):
    h, t = setup_task(client)
    assert t["source_type"] == "zip" and t["source_hash"] is None
    r = client.post(f"/api/v1/tasks/{t['id']}/start", headers=h)
    assert r.status_code == 409 and "upload" in r.json()["error"]["message"]
    up = upload(client, h, t["id"])
    assert up.status_code == 200
    body = up.json()
    assert len(body["source_hash"]) == 64 and body["source_ref"] == "repo.zip"
    imported = events(client, h, t["id"], "repo_imported")[0]
    assert imported["files"] == 3 and imported["secret_excluded"] == []


def test_source_endpoint_guards(client):
    h, plain = setup_task(client, source_type="none", email="a@x.com")
    assert upload(client, h, plain["id"]).status_code == 409  # not a zip task
    h2, t = setup_task(client, email="b@x.com")
    assert upload(client, h, t["id"]).status_code == 404  # another user's task
    assert upload(client, h2, t["id"], files={"logo.png": "x"}).status_code == 422
    bad = client.post(
        f"/api/v1/tasks/{t['id']}/source",
        files={"file": ("x.zip", b"not a zip", "application/zip")},
        headers=h2,
    )
    assert bad.status_code == 422
    assert upload(client, h2, t["id"]).status_code == 200


def test_language_mismatch_is_rejected(client):
    h, t = setup_task(client, language="javascript", email="c@x.com")
    r = upload(client, h, t["id"])  # a Python repo into a JavaScript project
    assert r.status_code == 422 and "looks like python" in r.json()["error"]["message"]


def test_task_create_validation(client):
    h = register_and_login(client, "v@x.com")
    p = client.post("/api/v1/projects", json={"name": "x"}, headers=h).json()
    base = {"project_id": p["id"], "requirement": "r"}
    for bad in (
        {"source_type": "git"},
        {"source_type": "zip", "git_url": "https://github.com/a/b"},
        {"source_type": "git", "git_url": "file:///etc/passwd"},
        {"source_type": "git", "git_url": "https://u:p@github.com/a/b"},
        {"source_type": "svn"},
    ):
        assert client.post("/api/v1/tasks", json={**base, **bad}, headers=h).status_code == 422
    url = "https://github.com/a/b"
    ok = client.post(
        "/api/v1/tasks", json={**base, "source_type": "git", "git_url": url}, headers=h
    )
    assert ok.status_code == 201 and ok.json()["source_ref"] == url
    cobol = client.post("/api/v1/projects", json={"name": "y", "language": "cobol"}, headers=h)
    assert cobol.status_code == 422
    ts = client.post("/api/v1/projects", json={"name": "z", "language": "TypeScript"}, headers=h)
    assert ts.json()["language"] == "javascript"


# ---- end to end: fix a seeded bug offline -------------------------------------------------


def test_repo_input_task_fixes_seeded_bug_end_to_end(client):
    h, t = setup_task(client)
    upload(client, h, t["id"])
    client.llm.queue(plan(), patch(), review())
    sandbox = ScriptedSandbox([passing_report(3)])
    assert run_loop(client, t["id"], sandbox) == "COMPLETED"

    tid = uuid.UUID(t["id"])
    it1 = workspace.iteration_dir(tid, 1)
    assert (it1 / "app/calc.py").read_text() == FIXED
    assert (it1 / "tests/test_calc.py").read_text() == TESTS  # untouched files carried over
    assert (it1 / "README.md").exists()
    assert workspace.read_seed(tid)["app/calc.py"] == BUGGY  # the seed is never modified

    diff = workspace.diff_iterations(tid, 0, 1)
    assert [d["path"] for d in diff] == ["app/calc.py"]
    assert "-    return a - b" in diff[0]["diff"]

    planner_call, builder_call = client.llm.calls[0], client.llm.calls[1]
    assert "Existing repository map" in planner_call.user and "app/calc.py" in planner_call.user
    assert "EXISTING repository" in planner_call.system
    assert BUGGY.strip() in builder_call.user  # current content of the file being modified
    assert "README.md" not in builder_call.user
    assert sandbox.workspaces[0] == it1  # tests ran on the patched tree, not the seed


def test_repo_task_repair_loop_starts_from_the_patched_tree(client):
    h, t = setup_task(client, email="rep@x.com")
    upload(client, h, t["id"])
    client.llm.queue(plan(), patch(content=BUGGY + "# still wrong\n"), fix_repair(), review())
    failing = failing_report()
    failing["summary"]["total"] = 3
    assert run_loop(client, t["id"], ScriptedSandbox([failing, passing_report(3)])) == "COMPLETED"
    it2 = workspace.iteration_dir(uuid.UUID(t["id"]), 2)
    assert (it2 / "app/calc.py").read_text() == FIXED
    assert (it2 / "tests/test_calc.py").exists()


def test_planner_output_inconsistent_with_repo_is_rejected(client):
    h, t = setup_task(client, email="bad@x.com")
    upload(client, h, t["id"])
    ghost = [planned("app/ghost.py")]
    client.llm.queue(plan(files=ghost), plan(files=ghost))  # initial + corrective retry
    assert run_loop(client, t["id"], ScriptedSandbox([passing_report(3)])) == "FAILED"
    with Session(client.engine) as s:
        rejected = [
            str(e.event_data)
            for e in s.scalars(select(AuditEvent))
            if e.event_type == "agent_output_rejected"
        ]
    assert any("not in the repository" in r for r in rejected)


def test_builder_must_return_exactly_the_planned_files(client):
    h, t = setup_task(client, email="ex@x.com")
    upload(client, h, t["id"])
    extra_file = {"path": "app/extra.py", "content": "x = 1\n", "action": "create"}
    extra = {"files": [*patch()["files"], extra_file]}
    client.llm.queue(plan(), extra, extra)
    assert run_loop(client, t["id"], ScriptedSandbox([passing_report(3)])) == "FAILED"


def test_deleting_existing_tests_cannot_pass(client):
    h, t = setup_task(client, email="del@x.com")
    upload(client, h, t["id"])
    files = [planned("app/calc.py"), planned("tests/test_calc.py")]
    gutted = {
        "files": [
            {"path": "app/calc.py", "content": FIXED, "action": "modify"},
            {
                "path": "tests/test_calc.py",
                "content": "def test_one():\n    assert True\n",
                "action": "modify",
            },
        ]
    }
    client.llm.queue(plan(files=files), gutted, review())
    # The baseline is the repository's own 2 tests: a green run with only 1 is not accepted.
    assert run_loop(client, t["id"], ScriptedSandbox([passing_report(1)])) == "ESCALATED"


def test_secret_file_never_reaches_the_model(client):
    h, t = setup_task(client, email="sec@x.com")
    leaked = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    up = upload(client, h, t["id"], files={**SEED, "app/settings.py": f"KEY = '{leaked}'\n"})
    assert up.status_code == 200
    excluded = events(client, h, t["id"], "repo_imported")[0]["secret_excluded"]
    assert excluded == [{"path": "app/settings.py", "kinds": ["OpenAI-style API key"]}]
    client.llm.queue(plan(), patch(), review())
    assert run_loop(client, t["id"], ScriptedSandbox([passing_report(3)])) == "COMPLETED"
    for call in client.llm.calls:
        assert leaked not in call.user and leaked not in call.system
        assert "app/settings.py" not in call.user
    assert not (workspace.iteration_dir(uuid.UUID(t["id"]), 1) / "app/settings.py").exists()


def test_git_task_import_failure_fails_cleanly(client, monkeypatch):
    url = "https://github.com/a/b"
    h, t = setup_task(client, source_type="git", git_url=url, email="g@x.com")

    def boom(_url):
        raise repo_import.RepoImportError("git clone failed (repository missing or not public)")

    monkeypatch.setattr(repo_import, "import_git", boom)
    assert run_loop(client, t["id"], ScriptedSandbox([passing_report(3)])) == "FAILED"
    reason = events(client, h, t["id"], "run_failed")[0]["reason"]
    assert "repository import failed" in reason
    assert client.llm.calls == []  # nothing was sent to a model


def test_git_task_success_path(client, monkeypatch):
    monkeypatch.setattr(
        repo_import, "import_git", lambda _u: repo_import.import_zip(make_zip(SEED))
    )
    url = "https://github.com/a/b"
    h, t = setup_task(client, source_type="git", git_url=url, email="g2@x.com")
    client.llm.queue(plan(), patch(), review())
    assert run_loop(client, t["id"], ScriptedSandbox([passing_report(3)])) == "COMPLETED"
    task = client.get(f"/api/v1/tasks/{t['id']}", headers=h).json()
    assert task["source_hash"] and task["source_ref"] == url


# ---- JavaScript (greenfield) --------------------------------------------------------------

JS_PLAN = {
    "project_name": "calc_js",
    "framework": "Node.js",
    "requirements": REQ,
    "acceptance_criteria": CRITERIA,
    "files": [
        {"path": "package.json", "purpose": "manifest", "implements": []},
        {"path": "src/calc.js", "purpose": "add", "implements": ["REQ-001"]},
        {"path": "src/calc.test.js", "purpose": "tests", "implements": ["REQ-001"]},
    ],
    "dependencies": [],
}
PKG = '{"name":"calc","devDependencies":{"jest":"29.7.0"}}\n'
CALC = "exports.add = (a, b) => a + b;\n"
CALC_TEST = "test('add', () => expect(require('./calc').add(1, 2)).toBe(3));\n"


def js_build(pkg=PKG):
    return {
        "files": [
            {"path": "package.json", "content": pkg, "action": "create"},
            {"path": "src/calc.js", "content": CALC, "action": "create"},
            {"path": "src/calc.test.js", "content": CALC_TEST, "action": "create"},
        ]
    }


def test_javascript_greenfield_flow_uses_jest_and_eslint(client):
    h, t = setup_task(client, language="javascript", source_type="none", email="js@x.com")
    client.llm.queue(JS_PLAN, js_build(), review())
    sandbox = ScriptedSandbox([jest_passing_report(3)])
    assert run_loop(client, t["id"], sandbox) == "COMPLETED"
    assert sandbox.calls[0][0] == "jest" and any(c[0] == "eslint" for c in sandbox.calls)
    assert not any(c[0] in ("ruff", "bandit") for c in sandbox.calls)
    assert "Jest" in client.llm.calls[0].system and "package.json" in client.llm.calls[0].system
    it = client.get(f"/api/v1/tasks/{t['id']}/iterations", headers=h).json()
    assert it[0]["tests"]["passed"] == 3 and it[0]["tests"]["failed"] == 0


def test_javascript_dependency_policy_blocks_before_execution(client):
    h, t = setup_task(client, language="javascript", source_type="none", email="jsd@x.com")
    client.llm.queue(JS_PLAN, js_build('{"dependencies":{"left-pad":"1.3.0"}}'))
    sandbox = ScriptedSandbox([jest_passing_report(3)])
    run_loop(client, t["id"], sandbox)  # then the (unqueued) repair call fails the run
    assert sandbox.pytest_runs == 0  # jest never ran
    with Session(client.engine) as s:
        row = s.scalars(select(TestResult)).first()
        assert row.details["blocked"] == "dependency policy"
        assert any("left-pad" in v and "not approved" in v for v in row.details["violations"])


def test_javascript_failure_reaches_repair_with_jest_details(client):
    h, t = setup_task(client, language="javascript", source_type="none", email="jsf@x.com")
    client.llm.queue(JS_PLAN, js_build(), fix_repair("src/calc.js", CALC), review())
    sandbox = ScriptedSandbox([jest_failing_report(), jest_passing_report(3)])
    assert run_loop(client, t["id"], sandbox) == "COMPLETED"
    repair_call = next(c for c in client.llm.calls if "Repair" in c.system)
    assert "src/a.test.js::subtracts" in repair_call.user
    assert "AssertionError" in repair_call.user


def test_python_greenfield_still_uses_the_python_prompts(client):
    from app.demo.employee_management import DEMO_REQUIREMENT, demo_responses

    h = register_and_login(client, "py@x.com")
    p = client.post("/api/v1/projects", json={"name": "e"}, headers=h).json()
    body = {"project_id": p["id"], "requirement": DEMO_REQUIREMENT}
    t = client.post("/api/v1/tasks", json=body, headers=h).json()
    client.llm.queue(*demo_responses())
    client.post(f"/api/v1/tasks/{t['id']}/start", headers=h)
    first = client.llm.calls[0]
    assert "Python FastAPI application" in first.system
    assert "EXISTING repository" not in first.system
