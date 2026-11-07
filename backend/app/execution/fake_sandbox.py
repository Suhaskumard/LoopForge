"""Deterministic in-process stand-in for tests and demos (forbidden in production by config).

It never executes anything: it writes a canned pytest-json-report into `out_dir`.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.execution.sandbox import ExecResult


def passing_report(n: int = 3) -> dict[str, Any]:
    return {
        "summary": {"passed": n, "total": n, "collected": n},
        "tests": [{"nodeid": f"tests/test_x.py::test_{i}", "outcome": "passed"} for i in range(n)],
    }


def failing_report() -> dict[str, Any]:
    trace = "def test_boom():\n>       assert 1 == 2\nE       assert 1 == 2\n"
    return {
        "summary": {"passed": 1, "failed": 1, "total": 2, "collected": 2},
        "tests": [
            {"nodeid": "tests/test_x.py::test_ok", "outcome": "passed"},
            {
                "nodeid": "tests/test_x.py::test_boom",
                "outcome": "failed",
                "call": {"longrepr": trace, "crash": {"message": "assert 1 == 2"}},
            },
        ],
    }


class FakeSandbox:
    def __init__(
        self,
        report: dict[str, Any] | None = None,
        *,
        exit_code: int | None = None,
        timed_out: bool = False,
        stdout: str = "fake run\n",
        stderr: str = "",
        hook: Callable[[Path, list[str]], None] | None = None,
    ) -> None:
        self.report = passing_report() if report is None and not timed_out else report
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.stdout, self.stderr = stdout, stderr
        self.hook = hook
        self.calls: list[list[str]] = []

    def run(self, workspace: Path, out_dir: Path, argv: list[str], timeout: int) -> ExecResult:
        self.calls.append(argv)
        if self.hook:
            self.hook(workspace, argv)
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.report is not None:
            (out_dir / "report.json").write_text(json.dumps(self.report), encoding="utf-8")
        failed = bool(self.report and self.report["summary"].get("failed"))
        code = self.exit_code if self.exit_code is not None else (1 if failed else 0)
        if self.timed_out:
            code = 124
        return ExecResult(self.stdout, self.stderr, code, self.timed_out, 0.01)
