import json

from app.evaluation.test_runner import parse_report
from app.execution.dependencies import check_requirements, load_approved
from app.execution.fake_sandbox import failing_report, passing_report
from app.execution.sandbox import ExecResult


def res(code=0, timed_out=False, stderr="", stdout=""):
    return ExecResult(stdout, stderr, code, timed_out, 0.1)


def test_parse_passing():
    s = parse_report(json.dumps(passing_report(4)), res(), 30)
    assert (s.total, s.passed, s.failed) == (4, 4, 0) and s.ok


def test_parse_failure_keeps_stack_trace():
    s = parse_report(json.dumps(failing_report()), res(1), 30)
    assert s.failed == 1 and not s.ok
    f = s.failures[0]
    assert f.nodeid.endswith("test_boom") and "assert 1 == 2" in f.traceback


def test_parse_collection_error_counts_as_failure():
    rep = {
        "summary": {"error": 1, "total": 0, "collected": 0},
        "collectors": [
            {"nodeid": "tests/test_x.py", "outcome": "failed", "longrepr": "SyntaxError"}
        ],
    }
    s = parse_report(json.dumps(rep), res(2), 30)
    assert s.failed == 1 and "SyntaxError" in s.failures[0].traceback and not s.ok


def test_missing_report_is_a_reported_failure_never_success():
    s = parse_report("", res(1, stderr="Traceback ...boom"), 30)
    assert not s.ok and not s.report_found and "boom" in s.failures[0].traceback


def test_timeout_is_reported():
    s = parse_report("", res(124, timed_out=True), 30)
    assert s.timed_out and not s.ok and "exceeded 30s" in s.failures[0].message


def test_empty_suite_is_not_ok():
    assert not parse_report(json.dumps({"summary": {"total": 0}}), res(5), 30).ok


def test_dependency_policy():
    approved = load_approved()
    assert "fastapi" in approved
    pinned = "\n".join(f"{n}=={v}" for n, v in approved.items())
    assert check_requirements(pinned) == []
    bad = check_requirements("requests==2.0\nfastapi\nuvicorn[standard]==9.9.9\n-e git+http://x\n")
    assert len(bad) == 4
    assert any("not approved" in v for v in bad) and any("pinned" in v for v in bad)
