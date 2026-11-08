"""Pytest execution inside the sandbox and machine-readable report parsing (3.4).

Everything here derives from real execution output. If there is no report (crash, timeout,
syntax error) that fact is itself reported as a failure; nothing is ever invented.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluation import go_report
from app.evaluation.classifier import extract_error_type
from app.execution.languages import GO, JAVASCRIPT, PYTHON, LanguageProfile, jest_counts
from app.execution.runner import run_command
from app.execution.sandbox import ExecResult, Sandbox

REPORT_NAME = "report.json"
COVERAGE_NAME = "coverage.json"
PYTEST_ARGV = list(PYTHON.test_argv)
_ANSI = re.compile("" + r"\[[0-9;]*m")
MAX_TRACE_CHARS = 6000


@dataclass
class TestFailure:
    __test__ = False
    nodeid: str
    message: str
    traceback: str
    error_type: str = ""

    def __post_init__(self) -> None:
        if not self.error_type:
            self.error_type = extract_error_type(self.message, self.traceback)


@dataclass
class TestSummary:
    __test__ = False
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    exit_code: int = 0
    timed_out: bool = False
    report_found: bool = False
    coverage: float | None = None
    duration_seconds: float = 0.0
    failures: list[TestFailure] = field(default_factory=list)
    # Phase 16: True when only the tests affected by a change were run (a failing subset). Such a
    # result is a repair signal, never a verdict: the suite-shrink guard must not read it as
    # "tests deleted".
    partial: bool = False

    @property
    def ok(self) -> bool:
        return self.report_found and not self.timed_out and self.failed == 0 and self.total > 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TRACE_CHARS else text[:MAX_TRACE_CHARS] + "\n[truncated]"


def _longrepr(entry: dict[str, Any]) -> tuple[str, str]:
    for phase in ("call", "setup", "teardown"):
        part = entry.get(phase)
        if isinstance(part, dict) and part.get("outcome", "failed") != "passed":
            crash = part.get("crash") or {}
            return str(crash.get("message", "")), str(part.get("longrepr", ""))
    return "", str(entry.get("longrepr", ""))


def parse_report(raw: str, result: ExecResult, timeout: int) -> TestSummary:
    summary = TestSummary(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        duration_seconds=result.duration_seconds,
    )
    if result.timed_out:
        summary.failed = 1
        summary.failures.append(
            TestFailure(
                "<execution>", f"execution exceeded {timeout}s and was killed", _clip(result.stderr)
            )
        )
        return summary
    try:
        data = json.loads(raw)
        counts = data["summary"]
    except (ValueError, KeyError, TypeError):
        summary.failed = 1
        tail = (result.stderr or result.stdout)[-MAX_TRACE_CHARS:]
        summary.failures.append(
            TestFailure("<execution>", f"no test report produced (exit {result.exit_code})", tail)
        )
        return summary

    summary.report_found = True
    summary.passed = int(counts.get("passed", 0))
    summary.skipped = int(counts.get("skipped", 0))
    broken = int(counts.get("failed", 0)) + int(counts.get("error", 0))
    summary.total = int(counts.get("total", counts.get("collected", 0)))
    for t in data.get("tests", []):
        if t.get("outcome") in ("failed", "error"):
            msg, trace = _longrepr(t)
            summary.failures.append(TestFailure(str(t.get("nodeid", "")), msg, _clip(trace)))
    for c in data.get("collectors", []):
        if c.get("outcome") == "failed":
            summary.failures.append(
                TestFailure(
                    str(c.get("nodeid", "")), "collection error", _clip(str(c.get("longrepr", "")))
                )
            )
    summary.failed = max(broken, len(summary.failures))
    if summary.failed and not summary.total:
        summary.total = summary.failed
    return summary


def parse_go_report(result: ExecResult, timeout: int) -> TestSummary:
    """Normalise `go test -json` (stdout) into the TestSummary the other languages produce."""
    summary = TestSummary(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        duration_seconds=result.duration_seconds,
    )
    if result.timed_out:
        summary.failed = 1
        summary.failures.append(
            TestFailure(
                "<execution>", f"execution exceeded {timeout}s and was killed", _clip(result.stderr)
            )
        )
        return summary
    data = go_report.summarize(go_report.parse_events(result.stdout))
    if not data["found"]:
        summary.failed = 1
        tail = _ANSI.sub("", (result.stderr or result.stdout)[-MAX_TRACE_CHARS:])
        summary.failures.append(
            TestFailure("<execution>", f"no test report produced (exit {result.exit_code})", tail)
        )
        return summary
    summary.report_found = True
    summary.total, summary.passed = data["total"], data["passed"]
    summary.skipped, summary.failed = data["skipped"], data["failed"]
    for f in data["failures"]:
        summary.failures.append(TestFailure(f["nodeid"], f["message"], _clip(f["traceback"])))
    summary.failed = max(summary.failed, len(summary.failures))
    if summary.failed and not summary.total:
        summary.total = summary.failed  # a build failure counts as one failing "test"
    return summary


def parse_jest_report(raw: str, result: ExecResult, timeout: int) -> TestSummary:
    """Normalise Jest's `--json` output into the same TestSummary the pytest path produces."""
    summary = TestSummary(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        duration_seconds=result.duration_seconds,
    )
    if result.timed_out:
        summary.failed = 1
        summary.failures.append(
            TestFailure(
                "<execution>", f"execution exceeded {timeout}s and was killed", _clip(result.stderr)
            )
        )
        return summary
    try:
        data = json.loads(raw)
        counts = jest_counts(data)
        suites = data["testResults"]
    except (ValueError, KeyError, TypeError):
        summary.failed = 1
        tail = _ANSI.sub("", (result.stderr or result.stdout)[-MAX_TRACE_CHARS:])
        summary.failures.append(
            TestFailure("<execution>", f"no test report produced (exit {result.exit_code})", tail)
        )
        return summary

    summary.report_found = True
    summary.passed, summary.skipped, summary.total = (
        counts["passed"],
        counts["skipped"],
        counts["total"],
    )
    for suite in suites:
        name = str(suite.get("name", "")).replace("\\", "/").removeprefix("/workspace/")
        asserts = suite.get("assertionResults") or []
        for a in asserts:
            if a.get("status") == "failed":
                msgs = [_ANSI.sub("", str(m)) for m in a.get("failureMessages") or []]
                first = msgs[0].strip().splitlines()[0] if msgs and msgs[0].strip() else ""
                summary.failures.append(
                    TestFailure(
                        f"{name}::{a.get('fullName') or a.get('title', '')}",
                        first,
                        _clip(chr(10).join(msgs)),
                    )
                )
        if suite.get("status") == "failed" and not asserts:  # syntax/import error in the suite
            msg = _ANSI.sub("", str(suite.get("message", "")))
            summary.failures.append(TestFailure(name, "test suite failed to run", _clip(msg)))
    summary.failed = max(counts["failed"], len(summary.failures))
    if summary.failed and not summary.total:
        summary.total = summary.failed
    return summary


def parse_js_coverage(path: Path) -> float | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return round(float(data["total"]["lines"]["pct"]), 2)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def run_tests(
    sandbox: Sandbox,
    workspace: Path,
    out_dir: Path,
    timeout: int,
    profile: LanguageProfile = PYTHON,
    only: list[str] | None = None,
) -> tuple[TestSummary, ExecResult]:
    report = out_dir / profile.report_name
    coverage = out_dir / profile.coverage_name
    report.unlink(missing_ok=True)
    coverage.unlink(missing_ok=True)
    result = run_command(sandbox, workspace, out_dir, [*profile.test_argv, *(only or [])], timeout)
    raw = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
    if profile is GO:
        summary = parse_go_report(result, timeout)
        summary.coverage = go_report.parse_coverprofile(coverage)
    elif profile is JAVASCRIPT:
        summary = parse_jest_report(raw, result, timeout)
        summary.coverage = parse_js_coverage(coverage)
    else:
        summary = parse_report(raw, result, timeout)
        summary.coverage = parse_coverage(coverage)
    summary.partial = bool(only)
    return summary, result


def parse_coverage(path: Path) -> float | None:
    """Total line coverage percent from coverage.py's JSON report, or None if unavailable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return round(float(data["totals"]["percent_covered"]), 2)
    except (OSError, ValueError, KeyError, TypeError):
        return None
