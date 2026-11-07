"""Pytest execution inside the sandbox and machine-readable report parsing (3.4).

Everything here derives from real execution output. If there is no report (crash, timeout,
syntax error) that fact is itself reported as a failure; nothing is ever invented.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.execution.runner import run_command
from app.execution.sandbox import ExecResult, Sandbox

REPORT_NAME = "report.json"
PYTEST_ARGV = [
    "python", "-m", "pytest", "-q", "--tb=short",
    "-p", "no:cacheprovider",
    "--json-report", "--json-report-file=/out/report.json",
    "--rootdir=/workspace",
]  # fmt: skip
MAX_TRACE_CHARS = 6000


@dataclass
class TestFailure:
    __test__ = False
    nodeid: str
    message: str
    traceback: str


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
    duration_seconds: float = 0.0
    failures: list[TestFailure] = field(default_factory=list)

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


def run_tests(
    sandbox: Sandbox, workspace: Path, out_dir: Path, timeout: int
) -> tuple[TestSummary, ExecResult]:
    report = out_dir / REPORT_NAME
    report.unlink(missing_ok=True)
    result = run_command(sandbox, workspace, out_dir, PYTEST_ARGV, timeout)
    raw = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
    return parse_report(raw, result, timeout), result
