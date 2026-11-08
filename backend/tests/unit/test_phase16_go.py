# ruff: noqa: E501  (long Go snippets are clearer unwrapped)
"""Phase 16: the Go language adapter (pure parsing and policy; no Go toolchain needed)."""

import json
from pathlib import Path

import pytest

from app.agents.repair_context import select_context
from app.agents.repo_map import build_repo_map
from app.config import settings
from app.evaluation import go_report
from app.evaluation.failure_class import classify_failure
from app.evaluation.quality import run_quality
from app.evaluation.test_guard import detect_test_weakening
from app.evaluation.test_runner import parse_go_report, run_tests
from app.execution.languages import (
    GO,
    PYTHON,
    detect_language,
    get_profile,
    image_for_argv,
)
from app.execution.runner import CommandNotAllowed, validate_command
from app.execution.sandbox import ExecResult


def ev(action: str, test: str | None = None, output: str | None = None, pkg: str = "x/lib") -> str:
    d: dict[str, object] = {"Action": action, "Package": pkg}
    if test:
        d["Test"] = test
    if output is not None:
        d["Output"] = output
    return json.dumps(d)


def result(stdout: str, stderr: str = "", code: int = 0, timed_out: bool = False) -> ExecResult:
    return ExecResult(
        stdout=stdout, stderr=stderr, exit_code=code, timed_out=timed_out, duration_seconds=0.1
    )


PASSING = "\n".join(
    [ev("run", "TestA"), ev("pass", "TestA"), ev("run", "TestB"), ev("pass", "TestB")]
)
FAILING = "\n".join(
    [
        ev("run", "TestA"),
        ev("pass", "TestA"),
        ev("run", "TestB"),
        ev("output", "TestB", "    b_test.go:9: got 1, want 2\n"),
        ev("fail", "TestB"),
        ev("fail"),
    ]
)
BUILD_FAIL = "\n".join(
    [ev("output", None, "lib/a.go:3:1: syntax error: unexpected }\n"), ev("fail")]
)


# ---- profile and policy -----------------------------------------------------------------------


def test_the_go_profile_is_registered_with_aliases():
    assert get_profile("go") is GO and get_profile("Golang") is GO
    assert GO.manifest == "go.mod" and GO.is_test_file("lib/x_test.go")
    assert not GO.is_test_file("lib/x.go")
    src = {"lib/a_test.go": "func TestA(t *testing.T) {}\nfunc TestB(t *testing.T) {}\n"}
    assert GO.count_tests(src) == 2


def test_go_mod_policy_allows_stdlib_only():
    ok = "module example.com/task\n\ngo 1.22\n"
    assert GO.check_dependencies(ok) == []
    bad = ok + "require github.com/evil/pkg v1.0.0\nreplace a => ../b\ntoolchain go1.30\n"
    problems = GO.check_dependencies(bad)
    assert "module not approved: github.com/evil/pkg" in problems
    assert "go.mod directive not allowed: replace" in problems
    assert "go.mod directive not allowed: toolchain" in problems
    block = "module m\n\nrequire (\n\tgithub.com/a/b v1.2.3\n)\n"
    assert GO.check_dependencies(block) == ["module not approved: github.com/a/b"]


def test_approved_go_modules_file_is_empty_so_only_the_standard_library_is_allowed():
    assert go_report is not None
    from app.execution.languages import load_approved_go

    assert load_approved_go() == set()


def test_go_commands_are_allowlisted_narrowly():
    validate_command(list(GO.test_argv))
    validate_command(list(GO.lint_argv))
    for argv in (
        ["go", "run", "./..."],
        ["go", "get", "github.com/x/y"],
        ["go", "build", "./..."],
        ["go", "test", "-exec", "/bin/sh"],
        ["go", "test", "-coverprofile=/etc/passwd"],
        ["go", "generate", "./..."],
    ):
        with pytest.raises(CommandNotAllowed):
            validate_command(argv)


def test_go_commands_use_the_go_image(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_image_go", "go-image")
    assert image_for_argv(list(GO.test_argv)) == "go-image"
    assert image_for_argv(["python", "-m", "pytest"]) == PYTHON.image


def test_detect_language_recognises_go_modules():
    assert detect_language({"go.mod": "module m", "main.go": "package main"}) == "go"
    assert detect_language({"go.mod": "m", "requirements.txt": "x", "a.py": ""}) == "python"


# ---- test results -----------------------------------------------------------------------------


def test_passing_events_become_a_clean_summary():
    s = parse_go_report(result(PASSING), 60)
    assert (s.total, s.passed, s.failed, s.report_found) == (2, 2, 0, True)
    assert s.ok


def test_failing_events_carry_the_test_name_and_message():
    s = parse_go_report(result(FAILING, code=1), 60)
    assert (s.total, s.passed, s.failed) == (2, 1, 1)
    f = s.failures[0]
    assert f.nodeid == "x/lib::TestB" and "got 1, want 2" in f.message
    assert not s.ok


def test_a_package_that_does_not_compile_is_one_failure():
    s = parse_go_report(result(BUILD_FAIL, code=1), 60)
    assert s.failed == 1 and s.total == 1
    assert s.failures[0].nodeid.endswith("::<build>") and "syntax error" in s.failures[0].message


def test_no_output_and_timeouts_are_reported_not_hidden():
    none = parse_go_report(result("", stderr="go: command not found", code=127), 60)
    assert none.failed == 1 and not none.report_found
    slow = parse_go_report(result("", timed_out=True), 5)
    assert slow.timed_out and "exceeded 5s" in slow.failures[0].message


def test_non_json_noise_between_events_is_ignored():
    s = parse_go_report(result("warning: something\n" + PASSING + "\nPASS\n"), 60)
    assert s.total == 2


def test_coverprofile_is_statement_weighted(tmp_path: Path):
    prof = tmp_path / "coverage.out"
    prof.write_text(
        "mode: set\nx/lib/a.go:3.1,5.2 3 1\nx/lib/a.go:6.1,8.2 1 0\nx/lib/b.go:1.1,2.2 6 4\n",
        encoding="utf-8",
    )
    assert go_report.parse_coverprofile(prof) == 90.0  # (3 + 6) / 10 statements
    assert go_report.parse_coverprofile(tmp_path / "missing") is None
    empty = tmp_path / "empty.out"
    empty.write_text("mode: set\n", encoding="utf-8")
    assert go_report.parse_coverprofile(empty) is None


class Scripted:
    def __init__(self, res: ExecResult) -> None:
        self.res, self.calls = res, []

    def run(self, workspace, out_dir, argv, timeout):
        self.calls.append(argv)
        (out_dir / "coverage.out").write_text("mode: set\na.go:1.1,2.2 2 1\n", encoding="utf-8")
        return self.res


def test_run_tests_for_go_reads_stdout_and_the_cover_profile(tmp_path: Path):
    sandbox = Scripted(result(PASSING))
    out = tmp_path / "out"
    out.mkdir()
    summary, _ = run_tests(sandbox, tmp_path, out, 30, GO)
    assert summary.ok and summary.coverage == 100.0
    assert sandbox.calls[0][:3] == ["go", "test", "-json"]


def test_run_tests_can_be_limited_to_named_test_files(tmp_path: Path):
    sandbox = Scripted(result(PASSING))
    out = tmp_path / "out"
    out.mkdir()
    summary, _ = run_tests(sandbox, tmp_path, out, 30, GO, only=["lib/"])
    assert summary.partial and sandbox.calls[0][-1] == "lib/"


# ---- quality, guard, context ------------------------------------------------------------------


def test_go_vet_findings_become_lint_items_and_failures_are_reported(tmp_path: Path):
    stderr = (
        "# x/lib\nlib/a.go:7:2: unreachable code\nlib/b.go:3: result of fmt.Sprintf call not used\n"
    )
    q = run_quality(Scripted(result("", stderr, code=2)), tmp_path, tmp_path, 30, GO)
    assert [(i["filename"], i["line"]) for i in q.ruff] == [("lib/a.go", 7), ("lib/b.go", 3)]
    assert q.bandit_high == [] and q.tool_errors == []
    broken = run_quality(Scripted(result("", "", code=127)), tmp_path, tmp_path, 30, GO)
    assert broken.tool_errors


def test_go_test_weakening_is_detected():
    old = {
        "lib/a_test.go": 'func TestA(t *testing.T) {\n\tt.Fatalf("x")\n}\nfunc TestB(t *testing.T) {\n\tt.Errorf("y")\n}\n'
    }
    new = {"lib/a_test.go": 'func TestA(t *testing.T) {\n\tt.Skip("later")\n}\n'}
    findings = " | ".join(detect_test_weakening(old, new, GO))
    assert "tests reduced from 2 to 1" in findings
    assert "assertions reduced" in findings and "adds skip" in findings
    assert detect_test_weakening(old, old, GO) == []


def test_go_failure_classes():
    syntax = [
        {
            "nodeid": "x::<build>",
            "message": "lib/a.go:3:1: syntax error: unexpected }",
            "traceback": "",
        }
    ]
    imp = [{"nodeid": "x::<build>", "message": 'cannot find package "foo"', "traceback": ""}]
    logic = [{"nodeid": "x::TestA", "message": "got 1, want 2", "traceback": ""}]
    assert classify_failure(syntax, GO) == "syntax"
    assert classify_failure(imp, GO) == "import"
    assert classify_failure(logic, GO) == "logic"


FILES = {
    "go.mod": "module example.com/task\n\ngo 1.22\n",
    "lib/a.go": "package lib\n\nfunc Add(a, b int) int { return a + b }\n\ntype Box struct{}\n",
    "lib/b.go": "package lib\n\nfunc (b Box) Size() int { return 1 }\n",
    "lib/a_test.go": "package lib\n\nfunc TestAdd(t *testing.T) {}\n",
    "cmd/main.go": "package main\n\nfunc main() {}\n",
}


def test_repo_map_lists_go_symbols_and_entry_points():
    m = build_repo_map(FILES, GO)
    assert m["language"] == "go"
    assert "Add" in m["symbols"]["lib/a.go"] and "Box" in m["symbols"]["lib/a.go"]
    assert "Size" in m["symbols"]["lib/b.go"]
    assert "cmd/main.go" in m["entry_points"]


def test_repair_context_pulls_in_the_rest_of_the_package():
    text = select_context(FILES, "lib/a.go:3: wrong", GO, max_chars=10_000)
    assert "--- lib/b.go\npackage lib" in text  # same package: sent in full
    assert "--- cmd/main.go (outline only" in text  # another package: outline only


def test_all_ten_go_benchmark_tasks_are_present_and_well_formed():
    root = Path(__file__).resolve().parents[3] / "benchmarks" / "tasks_go"
    dirs = sorted(d for d in root.iterdir() if d.is_dir())
    assert len(dirs) >= 10
    for d in dirs:
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        assert meta["language"] == "go" and meta["module"] in meta["requirement"]
        hidden = (d / "hidden_tests" / "hidden_test.go").read_text(encoding="utf-8")
        assert hidden.count("\nfunc Test") + hidden.startswith("func Test") >= 5
