"""Deterministic quality checks (4.3): Ruff lint and Bandit security scan, run in the sandbox.

Tool output is parsed defensively. A tool that fails to run is recorded in `tool_errors`; for the
security scan that is treated as an open high-severity finding, because "no scan" is not "no
vulnerabilities".
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluation import go_report
from app.execution.languages import GO, JAVASCRIPT, PYTHON, LanguageProfile
from app.execution.runner import run_command
from app.execution.sandbox import Sandbox

RUFF_ARGV = ["ruff", "check", "--output-format=json", "--no-cache", "/workspace"]
BANDIT_ARGV = ["bandit", "-r", "/workspace", "-f", "json", "-q", "-x", "/workspace/tests"]
MAX_ITEMS = 25


@dataclass
class QualityReport:
    ruff: list[dict[str, Any]] = field(default_factory=list)
    bandit_high: list[dict[str, Any]] = field(default_factory=list)
    bandit_other: int = 0
    tool_errors: list[str] = field(default_factory=list)

    @property
    def security_scan_failed(self) -> bool:
        return any(e.startswith("bandit") for e in self.tool_errors)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rel(filename: str) -> str:
    return filename.removeprefix("/workspace/")


def parse_ruff(stdout: str) -> list[dict[str, Any]]:
    data = json.loads(stdout or "[]")
    if not isinstance(data, list):
        raise ValueError("unexpected ruff output")
    return [
        {
            "code": str(d.get("code", "")),
            "message": str(d.get("message", ""))[:300],
            "file": _rel(str(d.get("filename", ""))),
            "line": (d.get("location") or {}).get("row", 0),
        }
        for d in data[:MAX_ITEMS]
    ]


def parse_bandit(stdout: str) -> tuple[list[dict[str, Any]], int]:
    data = json.loads(stdout)
    results = data["results"]
    high = [
        {
            "test_id": str(r.get("test_id", "")),
            "message": str(r.get("issue_text", ""))[:300],
            "file": _rel(str(r.get("filename", ""))),
            "line": r.get("line_number", 0),
        }
        for r in results
        if str(r.get("issue_severity", "")).upper() == "HIGH"
    ]
    return high[:MAX_ITEMS], len(results) - len(high)


def parse_eslint(stdout: str) -> list[dict[str, Any]]:
    data = json.loads(stdout or "[]")
    if not isinstance(data, list):
        raise ValueError("unexpected eslint output")
    items: list[dict[str, Any]] = []
    for f in data:
        for m in f.get("messages", []):
            items.append(
                {
                    "code": str(m.get("ruleId") or "parse-error"),
                    "message": str(m.get("message", ""))[:300],
                    "file": _rel(str(f.get("filePath", ""))),
                    "line": m.get("line", 0),
                }
            )
    return items[:MAX_ITEMS]


def _run_js_quality(
    sandbox: Sandbox, workspace: Path, out_dir: Path, timeout: int
) -> QualityReport:
    """ESLint only. There is no JS security scanner in the image: that gap is documented
    (ADR-0015), not hidden - `bandit_high` stays empty and no 'clean scan' is claimed."""
    report = QualityReport()
    res = run_command(sandbox, workspace, out_dir, list(JAVASCRIPT.lint_argv), timeout)
    try:
        if res.timed_out or res.exit_code not in (0, 1):
            raise ValueError("eslint did not complete")
        report.ruff = parse_eslint(res.stdout)
    except (ValueError, TypeError, AttributeError):
        report.tool_errors.append(f"eslint: unreadable output (exit {res.exit_code})")
    return report


def _run_go_quality(
    sandbox: Sandbox, workspace: Path, out_dir: Path, timeout: int
) -> QualityReport:
    """`go vet` only. There is no Go security scanner in the image: that gap is documented
    (ADR-0023), not hidden - `bandit_high` stays empty and no 'clean scan' is claimed."""
    report = QualityReport()
    res = run_command(sandbox, workspace, out_dir, list(GO.lint_argv), timeout)
    if res.timed_out or res.exit_code not in (0, 1, 2):
        report.tool_errors.append(f"go vet: did not complete (exit {res.exit_code})")
    else:
        report.ruff = go_report.parse_vet(res.stderr or res.stdout)
    return report


def run_quality(
    sandbox: Sandbox,
    workspace: Path,
    out_dir: Path,
    timeout: int,
    profile: LanguageProfile = PYTHON,
) -> QualityReport:
    if profile is GO:
        return _run_go_quality(sandbox, workspace, out_dir, timeout)
    if profile is JAVASCRIPT:
        return _run_js_quality(sandbox, workspace, out_dir, timeout)
    report = QualityReport()
    ruff_res = run_command(sandbox, workspace, out_dir, RUFF_ARGV, timeout)
    try:
        if ruff_res.timed_out or ruff_res.exit_code not in (0, 1):
            raise ValueError("ruff did not complete")
        report.ruff = parse_ruff(ruff_res.stdout)
    except (ValueError, TypeError):
        report.tool_errors.append(f"ruff: unreadable output (exit {ruff_res.exit_code})")
    bandit_res = run_command(sandbox, workspace, out_dir, BANDIT_ARGV, timeout)
    try:
        if bandit_res.timed_out:
            raise ValueError("bandit timed out")
        report.bandit_high, report.bandit_other = parse_bandit(bandit_res.stdout)
    except (ValueError, KeyError, TypeError):
        report.tool_errors.append(f"bandit: unreadable output (exit {bandit_res.exit_code})")
    return report
