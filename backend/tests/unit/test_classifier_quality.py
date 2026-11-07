import json

import pytest

from app.evaluation.classifier import (
    build_failure_report,
    classify_execution,
    classify_quality,
    classify_requirements,
    extract_error_type,
)
from app.evaluation.quality import parse_bandit, parse_ruff, run_quality
from app.evaluation.test_runner import parse_coverage
from app.execution.fake_sandbox import FakeSandbox, ScriptedSandbox
from app.execution.runner import CommandNotAllowed, validate_command
from app.execution.sandbox import ExecResult


@pytest.mark.parametrize(
    ("message", "trace", "expected"),
    [
        ("", "E   KeyError: 'k'\n", "KeyError"),
        ("", "E   app.models.ValidationError: bad", "ValidationError"),
        ("ModuleNotFoundError: no module", "", "ModuleNotFoundError"),
        ("assert 1 == 2", "E   assert 1 == 2", "AssertionError"),
        ("execution exceeded 30s and was killed", "", "Timeout"),
        ("something odd", "", "Unknown"),
    ],
)
def test_error_type_extraction(message, trace, expected):
    assert extract_error_type(message, trace) == expected


def test_error_type_ignores_line_numbers_and_values():
    a = extract_error_type("", "x.py:10\nE   KeyError: 'a'")
    b = extract_error_type("", "x.py:99\nE   KeyError: 'zzz'")
    assert a == b == "KeyError"


def test_three_channels_in_one_report():
    report = build_failure_report(
        [{"nodeid": "t::a", "message": "boom", "traceback": "E   ValueError: x"}],
        classify_quality(
            [{"code": "F401", "message": "unused"}], [{"test_id": "B602"}], coverage=40.0
        ),
        classify_requirements(
            [
                {"criterion": "auth", "met": False, "evidence": "no auth"},
                {"criterion": "x", "met": True},
            ]
        ),
    )
    assert report["execution"][0]["channel"] == "execution"
    assert report["execution"][0]["error_type"] == "ValueError"
    assert [q["tool"] for q in report["quality"]] == ["bandit", "ruff", "coverage"]
    assert report["requirement"] == [
        {"channel": "requirement", "criterion": "auth", "message": "no auth"}
    ]
    assert classify_quality([], [], None) == [] and classify_quality([], [], 90.0) == []
    assert classify_execution([]) == []


RUFF = json.dumps(
    [
        {
            "code": "F401",
            "message": "unused",
            "filename": "/workspace/app/a.py",
            "location": {"row": 3},
        }
    ]
)
BANDIT = json.dumps(
    {
        "results": [
            {
                "issue_severity": "HIGH",
                "test_id": "B602",
                "issue_text": "shell",
                "filename": "/workspace/a.py",
                "line_number": 4,
            },
            {
                "issue_severity": "LOW",
                "test_id": "B101",
                "issue_text": "assert",
                "filename": "/workspace/b.py",
            },
        ]
    }
)


def test_parsers():
    assert parse_ruff(RUFF) == [
        {"code": "F401", "message": "unused", "file": "app/a.py", "line": 3}
    ]
    assert parse_ruff("") == []
    high, other = parse_bandit(BANDIT)
    assert [h["test_id"] for h in high] == ["B602"] and other == 1
    with pytest.raises(ValueError):
        parse_ruff('{"not": "a list"}')
    with pytest.raises(ValueError):
        parse_bandit("not json")


def test_run_quality_collects_findings(tmp_path):
    sb = ScriptedSandbox(
        [{"summary": {}}],
        tool_outputs={
            "ruff": ExecResult(RUFF, "", 1, False, 0.1),
            "bandit": ExecResult(BANDIT, "", 1, False, 0.1),
        },
    )
    report = run_quality(sb, tmp_path, tmp_path / "out", 30)
    assert len(report.ruff) == 1 and len(report.bandit_high) == 1 and not report.tool_errors
    assert not report.security_scan_failed


@pytest.mark.parametrize(
    "tool_outputs",
    [
        {"bandit": ExecResult("", "crash", 2, False, 0.1)},
        {"bandit": ExecResult("", "", 124, True, 30)},
        {"ruff": ExecResult("", "crash", 2, False, 0.1)},
        {"ruff": ExecResult("", "", 124, True, 30)},
    ],
)
def test_tool_failure_is_recorded_never_treated_as_clean(tmp_path, tool_outputs):
    sb = ScriptedSandbox([{"summary": {}}], tool_outputs=tool_outputs)
    report = run_quality(sb, tmp_path, tmp_path, 30)
    assert report.tool_errors
    assert report.security_scan_failed == ("bandit" in tool_outputs)


def test_fake_sandbox_quality_tools_are_clean(tmp_path):
    report = run_quality(FakeSandbox(), tmp_path, tmp_path, 30)
    assert report.as_dict() == {"ruff": [], "bandit_high": [], "bandit_other": 0, "tool_errors": []}


def test_coverage_parser(tmp_path):
    p = tmp_path / "coverage.json"
    assert parse_coverage(p) is None
    p.write_text(json.dumps({"totals": {"percent_covered": 87.456}}))
    assert parse_coverage(p) == 87.46
    p.write_text("garbage")
    assert parse_coverage(p) is None


def test_allowlist_covers_quality_tools_and_nothing_else():
    validate_command(["ruff", "check", "--output-format=json", "--no-cache", "/workspace"])
    validate_command(["bandit", "-r", "/workspace", "-f", "json", "-q", "-x", "/workspace/tests"])
    for bad in (
        ["bandit", "-r", "/etc"],
        ["bandit", "--exit-zero"],
        ["bandit", "-r", "/workspace", "-c", "evil.yml"],
        ["ruff", "format", "/workspace"],
        ["ruff", "check", "--fix", "/workspace"],
        ["python", "-m", "pytest", "--cov=/etc"],
        ["coverage", "run"],
    ):
        with pytest.raises(CommandNotAllowed):
            validate_command(bad)
