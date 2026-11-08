"""Phase 16: the new switches (all default off), patch edits, affected-tests-first, verification
checks and safe memory. Everything here runs on fakes: nothing is measured on a real model."""

import hashlib
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents import repair
from app.config import settings
from app.database.models import RepairHistory, Task, TestResult
from app.demo.employee_management import (
    defective_builder_output,
    failing_update_report,
    passing_report_for_demo,
    repair_output,
    review_output,
)
from app.evaluation import mutation
from app.evaluation.affected_tests import affected_tests
from app.evaluation.changed_coverage import changed_line_coverage, changed_lines, read_line_coverage
from app.execution.languages import JAVASCRIPT, PYTHON
from app.orchestrator.decision import evaluate_iteration
from app.orchestrator.loop_config import E3, PHASE16_SWITCHES, PRESETS
from app.schemas.loop import PatchedFile, RepairPatchOutput, TextEdit
from app.services import workspace
from app.services.workspace import PatchConflict, apply_edits
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import PLAN
from tests.integration.test_phase6_controls import run_with, status_of

API = "/api/v1"
ROUTES_DEFECT = next(f for f in defective_builder_output().files if f.path == "app/routes.py")
ROUTES_FIXED = next(c for c in repair_output().changes if c.path == "app/routes.py")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- switches ---------------------------------------------------------------------------------


def test_every_phase_16_switch_is_off_in_production_defaults():
    assert all(getattr(E3, name) is False for name in PHASE16_SWITCHES)


def test_each_q_preset_turns_exactly_one_switch_on_and_p5_all():
    for i, name in enumerate(PHASE16_SWITCHES, start=1):
        cfg = PRESETS[f"Q{i}"]
        assert [n for n in PHASE16_SWITCHES if getattr(cfg, n)] == [name]
    assert all(getattr(PRESETS["P5"], n) for n in PHASE16_SWITCHES)


def test_phase_9_presets_still_leave_phase_16_off():
    for name in ("E1", "E2", "E3", "A1", "A2", "A3", "A4", "P0", "P1", "P2", "P3", "P4"):
        assert not any(getattr(PRESETS[name], n) for n in PHASE16_SWITCHES), name


# ---- patch edits ------------------------------------------------------------------------------


def test_apply_edits_is_exact_unique_and_atomic():
    text = "a = 1\nb = 2\nc = 3\n"
    base = sha(text)
    assert apply_edits("m.py", text, base, [("b = 2", "b = 20")]) == "a = 1\nb = 20\nc = 3\n"
    both = apply_edits("m.py", text, base, [("a = 1", "a = 10"), ("c = 3", "c = 30")])
    assert both == "a = 10\nb = 2\nc = 30\n"
    with pytest.raises(PatchConflict, match="hash differs"):
        apply_edits("m.py", text + "x", base, [("a = 1", "a = 2")])
    with pytest.raises(PatchConflict, match="not found"):
        apply_edits("m.py", text, base, [("zzz", "y")])
    with pytest.raises(PatchConflict, match="occurs 2 times"):
        apply_edits("m.py", "x\nx\n", sha("x\nx\n"), [("x", "y")])
    with pytest.raises(PatchConflict, match="overlap"):
        apply_edits("m.py", text, base, [("a = 1\nb", "q"), ("b = 2", "r")])


def test_edits_match_the_original_not_each_others_output():
    text = "one two"
    out = apply_edits("m.py", text, sha(text), [("one", "two"), ("two", "three")])
    assert out == "two three"


def _patch(path: str, base: str, search: str, replace: str) -> RepairPatchOutput:
    return RepairPatchOutput(
        root_cause="The update route looks up employee_id + 1.",
        explanation="Use the requested employee_id.",
        patches=[
            PatchedFile(
                path=path, base_sha256=base, edits=[TextEdit(search=search, replace=replace)]
            )
        ],
    )


def _defect_edit() -> tuple[str, str]:
    """The smallest unique piece of the injected defect and its fix."""
    start = next(
        i
        for i, (a, b) in enumerate(zip(ROUTES_DEFECT.content, ROUTES_FIXED.content, strict=False))
        if a != b
    )
    line_start = ROUTES_DEFECT.content.rfind("\n", 0, start) + 1
    line_end = ROUTES_DEFECT.content.index("\n", start)
    fixed_end = ROUTES_FIXED.content.index("\n", line_start)
    return (
        ROUTES_DEFECT.content[line_start:line_end],
        ROUTES_FIXED.content[line_start:fixed_end],
    )


def test_a_repair_sent_as_a_patch_fixes_the_task(client):
    search, replace = _defect_edit()
    cfg = PRESETS["Q2"]
    llm = [
        PLAN,
        defective_builder_output(),
        _patch("app/routes.py", sha(ROUTES_DEFECT.content), search, replace),
        review_output(),
    ]
    h, tid, _ = run_with(
        client, cfg, [failing_update_report(), passing_report_for_demo()], llm, "patch@x.com"
    )
    assert status_of(client, h, tid) == "COMPLETED"
    fixed = workspace.read_file(workspace.iteration_dir(uuid.UUID(tid), 2), "app/routes.py")
    assert fixed == ROUTES_FIXED.content
    prompt = next(c.user for c in client.llm.calls if c.response_model == "RepairPatchOutput")
    assert "File hashes (sha256)" in prompt and sha(ROUTES_DEFECT.content) in prompt


def test_a_conflicting_patch_is_rejected_and_the_agent_is_asked_again(client):
    search, replace = _defect_edit()
    llm = [
        PLAN,
        defective_builder_output(),
        _patch("app/routes.py", sha("some other version"), search, replace),  # stale hash
        _patch("app/routes.py", sha(ROUTES_DEFECT.content), search, replace),
        review_output(),
    ]
    h, tid, _ = run_with(
        client,
        PRESETS["Q2"],
        [failing_update_report(), passing_report_for_demo()],
        llm,
        "conflict@x.com",
    )
    assert status_of(client, h, tid) == "COMPLETED"
    asked = [c for c in client.llm.calls if c.response_model == "RepairPatchOutput"]
    assert len(asked) == 2 and "hash differs" in asked[1].user


def test_patch_mode_is_not_used_by_default(client):
    h, tid, _ = run_with(
        client,
        E3,
        [failing_update_report(), passing_report_for_demo()],
        [PLAN, defective_builder_output(), repair_output(), review_output()],
        "plain@x.com",
    )
    assert status_of(client, h, tid) == "COMPLETED"
    assert not [c for c in client.llm.calls if c.response_model == "RepairPatchOutput"]


# ---- affected tests first ---------------------------------------------------------------------


def test_affected_tests_by_name_import_and_self_change():
    files = {
        "app/routes.py": "",
        "app/models.py": "",
        "tests/test_routes.py": "from app.routes import router\n",
        "tests/test_api.py": "from app import models\n",
        "tests/test_other.py": "import json\n",
    }
    assert affected_tests(["app/routes.py"], files, PYTHON) == ["tests/test_routes.py"]
    assert affected_tests(["app/models.py"], files, PYTHON) == ["tests/test_api.py"]
    assert affected_tests(["tests/test_other.py"], files, PYTHON) == ["tests/test_other.py"]
    assert affected_tests(["README.md"], files, PYTHON) == []


def test_affected_tests_javascript_imports():
    files = {
        "src/math.js": "",
        "src/app.test.js": "const m = require('./math');\n",
        "src/other.test.js": "",
    }
    assert affected_tests(["src/math.js"], files, JAVASCRIPT) == ["src/app.test.js"]


def test_affected_first_runs_the_subset_then_always_the_full_suite(client):
    script = [failing_update_report(), passing_report_for_demo(), passing_report_for_demo()]
    llm = [PLAN, defective_builder_output(), repair_output(), review_output()]
    h, tid, sandbox = run_with(client, PRESETS["Q1"], script, llm, "aff@x.com")
    assert status_of(client, h, tid) == "COMPLETED"
    assert sandbox.pytest_runs == 3  # iteration 1 full, iteration 2 subset, then full
    pytest_calls = [c for c in sandbox.calls if c[:3] == ["python", "-m", "pytest"]]
    assert "tests/test_routes.py" in pytest_calls[1]
    assert "tests/test_routes.py" not in pytest_calls[2]
    with client.factory() as db:
        rows = db.scalars(select(TestResult).order_by(TestResult.created_at)).all()
    assert rows[-1].details["affected_first"] == ["tests/test_routes.py"]
    assert rows[-1].details.get("partial") is False


def test_a_failing_subset_is_a_signal_not_a_verdict(client):
    subset_fail = failing_update_report()
    subset_fail["tests"] = subset_fail["tests"][:2]  # fewer tests than the full suite
    script = [failing_update_report(), subset_fail, passing_report_for_demo()]
    llm = [PLAN, defective_builder_output(), repair_output(), repair_output(), review_output()]
    h, tid, sandbox = run_with(client, PRESETS["Q1"], script, llm, "sub@x.com")
    with client.factory() as db:
        rows = db.scalars(select(TestResult).order_by(TestResult.created_at)).all()
    partial = [r for r in rows if r.details.get("partial")]
    assert partial and "full suite not run" in partial[0].details["scope"]
    assert (
        status_of(client, h, tid) == "COMPLETED"
    )  # the smaller subset did not look like deleted tests


def test_a_partial_result_never_triggers_the_suite_shrink_guard():
    base = {
        "status": "tested",
        "iteration_in_run": 2,
        "max_iterations": 5,
        "best_test_count": 10,
        "review_results": {},
        "failure_fingerprints": [],
        "tokens_used": 0,
        "started_at": 0.0,
    }
    small = {
        "total_tests": 3,
        "passed": 2,
        "failed": 1,
        "skipped": 0,
        "timed_out": False,
        "failures": [],
    }
    from app.orchestrator.decision import Decision, Limits

    limits = Limits(max_tokens=10**6, max_task_seconds=900)
    full = evaluate_iteration({**base, "test_results": small}, limits, now=1.0)
    part = evaluate_iteration({**base, "test_results": {**small, "partial": True}}, limits, now=1.0)
    assert full is Decision.ESCALATE and part is not Decision.ESCALATE


# ---- changed-line coverage --------------------------------------------------------------------


def test_changed_lines_and_their_coverage(tmp_path: Path):
    old = {"app/a.py": "x = 1\ny = 2\n", "tests/test_a.py": "t\n"}
    new = {"app/a.py": "x = 1\ny = 3\nz = 4\n", "tests/test_a.py": "t\n", "app/new.py": "n = 1\n"}
    changed = changed_lines(old, new)
    assert changed == {"app/a.py": {2, 3}, "app/new.py": {1}}
    cov_file = tmp_path / "coverage.json"
    cov_file.write_text(
        '{"files": {"/workspace/app/a.py": {"executed_lines": [1, 2], "missing_lines": [3]},'
        ' "app/new.py": {"executed_lines": [], "missing_lines": [1]}}}',
        encoding="utf-8",
    )
    cov = read_line_coverage(cov_file)
    assert cov is not None
    result = changed_line_coverage(changed, cov)
    assert (result["covered"], result["executable"], result["ratio"]) == (1, 3, 0.3333)
    assert result["uncovered"] == {"app/a.py": [3], "app/new.py": [1]}
    assert read_line_coverage(tmp_path / "missing.json") is None
    assert changed_line_coverage({"app/x.py": {1}}, cov)["ratio"] is None  # unmeasured file


# ---- mutation check ---------------------------------------------------------------------------


SRC = "def f(a, b):\n    if a > b:\n        return a + b\n    return False\n"


def test_mutants_change_exactly_one_thing_and_stay_valid_python():
    ms = mutation.mutants_of("m.py", SRC, limit=10)
    assert {m.description for m in ms} >= {
        "flip comparison",
        "swap arithmetic operator",
        "return None",
        "negate boolean literal",
    }
    for m in ms:
        compile(m.source, "m.py", "exec")
        assert m.source != SRC
    assert mutation.mutants_of("m.py", SRC, limit=0) == []
    assert mutation.mutants_of("bad.py", "def (:", limit=3) == []
    assert len(mutation.mutants_of("m.py", SRC, limit=2)) == 2


def test_mutation_score_counts_mutants_the_tests_notice(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "m.py").write_text(SRC, encoding="utf-8")
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "scratch"))
    seen = {"n": 0}

    class Summary:
        def __init__(self, ok: bool) -> None:
            self.ok = ok

    def fake_run_tests(sandbox, scratch, out, timeout, profile):
        seen["n"] += 1
        assert (scratch / "app" / "m.py").read_text(
            encoding="utf-8"
        ) != SRC  # a mutant, not original
        return Summary(ok=seen["n"] % 2 == 0), None  # every other mutant survives

    monkeypatch.setattr(mutation, "run_tests", fake_run_tests)
    result = mutation.run_mutation_check(
        None, src, tmp_path / "out", ["app/m.py"], 5, max_mutants=4
    )  # type: ignore[arg-type]
    assert result["tried"] == 4 and result["killed"] == 2 and result["score"] == 0.5
    assert len(result["survivors"]) == 2
    assert (src / "app" / "m.py").read_text(encoding="utf-8") == SRC  # original untouched


def test_mutation_check_respects_its_time_budget(tmp_path: Path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text(SRC, encoding="utf-8")
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "scratch"))
    result = mutation.run_mutation_check(None, src, tmp_path / "o", ["m.py"], 5, budget_seconds=-1)  # type: ignore[arg-type]
    assert result == {"tried": 0, "killed": 0, "score": None, "survivors": []}


# ---- safe memory ------------------------------------------------------------------------------


def _task_in(client, h, project_id, learn=True):
    body = {
        "project_id": project_id,
        "requirement": "Build a thing with tests.",
        "learn_from_task": learn,
    }
    r = client.post(f"{API}/tasks", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _history(db, task_id, **over):
    row = RepairHistory(
        task_id=uuid.UUID(task_id), original_failure="f", failure_class="assertion",
        fingerprint="fp1", root_cause="cause", proposed_fix="fix", outcome="resolved", **over,
    )  # fmt: skip
    db.add(row)
    db.commit()
    return row


def test_opted_out_tasks_are_never_offered_as_hints(client):
    h = register_and_login(client, "mem@x.com")
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()["id"]
    teacher, optout, target = (
        _task_in(client, h, p),
        _task_in(client, h, p, learn=False),
        _task_in(client, h, p),
    )
    assert client.get(f"{API}/tasks/{optout}", headers=h).json()["learn_from_task"] is False
    with client.factory() as db:
        _history(db, teacher)
        _history(db, optout)
        got = repair._similar_fixes(db, db.get(Task, uuid.UUID(target)), "fp1", "assertion")
        assert {str(g.task_id) for g in got} == {teacher}


def test_memory_never_crosses_organizations(client):
    a = register_and_login(client, "orga@x.com")
    b = register_and_login(client, "orgb@x.com")
    pa = client.post(f"{API}/projects", json={"name": "p"}, headers=a).json()["id"]
    pb = client.post(f"{API}/projects", json={"name": "p"}, headers=b).json()["id"]
    ta, tb = _task_in(client, a, pa), _task_in(client, b, pb)
    with client.factory() as db:
        _history(db, ta)
        assert repair._similar_fixes(db, db.get(Task, uuid.UUID(tb)), "fp1", "assertion") == []


def test_expiry_only_applies_with_the_switch_and_a_ttl(client, monkeypatch):
    h = register_and_login(client, "ttl@x.com")
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()["id"]
    old_task, target = _task_in(client, h, p), _task_in(client, h, p)
    with client.factory() as db:
        row = _history(db, old_task)
        row.created_at = row.created_at - timedelta(days=40)
        db.commit()
        t = db.get(Task, uuid.UUID(target))
        monkeypatch.setattr(settings, "memory_ttl_days", 30)
        assert len(repair._similar_fixes(db, t, "fp1", "assertion", expiry=False)) == 1
        assert repair._similar_fixes(db, t, "fp1", "assertion", expiry=True) == []
        monkeypatch.setattr(settings, "memory_ttl_days", 0)  # 0 = never expire
        assert len(repair._similar_fixes(db, t, "fp1", "assertion", expiry=True)) == 1
        monkeypatch.setattr(settings, "memory_ttl_days", 60)
        assert len(repair._similar_fixes(db, t, "fp1", "assertion", expiry=True)) == 1
