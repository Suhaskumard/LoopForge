"""Decision Engine: every termination path (spec §11.4 requires 100% branch coverage)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.orchestrator.decision import (
    Decision,
    Limits,
    evaluate_iteration,
    failure_fingerprint,
    is_accepted,
)

LIMITS = Limits(max_tokens=30_000, max_task_seconds=900, max_attempts_per_failure=2)
CRITERION = {"criterion": "auth enforced", "met": True, "evidence": "ok"}


def green_tests(total=5):
    return {"total_tests": total, "passed": total, "failed": 0, "failures": []}


def red_tests(*names):
    names = names or ("t::a",)
    return {
        "total_tests": 5,
        "passed": 5 - len(names),
        "failed": len(names),
        "failures": [{"nodeid": n, "error_type": "AssertionError"} for n in names],
    }


def review_ok():
    return {
        "critical_issues": 0,
        "unapproved_high_severity": 0,
        "unverified_mandatory": 0,
        "acceptance_criteria": [CRITERION],
    }


def state(**kw):
    base = {
        "status": "tested",
        "test_results": green_tests(),
        "review_results": review_ok(),
        "iteration_in_run": 1,
        "max_iterations": 5,
        "tokens_used": 100,
        "started_at": 1000.0,
        "failure_fingerprints": [],
        "best_test_count": 0,
    }
    return {**base, **kw}


def decide(now=1010.0, **kw):
    return evaluate_iteration(state(**kw), LIMITS, now=now)


def test_accepts_when_everything_is_evidenced():
    assert decide() is Decision.COMPLETE


def test_cancelled_stops_even_if_everything_passes():
    assert decide(status="cancelled") is Decision.STOP


@pytest.mark.parametrize(
    "review_patch",
    [
        {"critical_issues": 1},
        {"unapproved_high_severity": 1},
        {"unverified_mandatory": 2},
        {"acceptance_criteria": [{**CRITERION, "met": False}]},
    ],
)
def test_each_unmet_condition_blocks_acceptance(review_patch):
    review = {**review_ok(), **review_patch}
    assert not is_accepted(green_tests(), review)
    assert decide(review_results=review) is Decision.RETRY


def test_failed_tests_or_empty_suite_block_acceptance():
    assert decide(test_results=red_tests()) is Decision.RETRY
    assert decide(test_results=green_tests(0)) is Decision.RETRY  # zero tests prove nothing


def test_legacy_review_without_unverified_key_still_evaluates():
    review = review_ok()
    del review["unverified_mandatory"]
    assert decide(review_results=review) is Decision.COMPLETE


def test_iteration_limit_escalates():
    assert decide(test_results=red_tests(), iteration_in_run=5) is Decision.ESCALATE
    assert decide(test_results=red_tests(), iteration_in_run=4) is Decision.RETRY


def test_token_limit_escalates():
    assert decide(test_results=red_tests(), tokens_used=30_000) is Decision.ESCALATE
    assert decide(test_results=red_tests(), tokens_used=29_999) is Decision.RETRY


def test_time_limit_escalates():
    assert decide(test_results=red_tests(), now=1900.0) is Decision.ESCALATE
    assert decide(test_results=red_tests(), now=1899.0) is Decision.RETRY


def test_default_clock_is_wall_time():
    assert evaluate_iteration(state(started_at=0.0, test_results=red_tests()), LIMITS) is (
        Decision.ESCALATE
    )


def test_identical_failure_repeating_escalates():
    bad = red_tests("t::a")
    fp = failure_fingerprint(bad, review_ok())
    assert decide(test_results=bad, failure_fingerprints=[fp]) is Decision.RETRY
    assert decide(test_results=bad, failure_fingerprints=[fp, fp]) is Decision.ESCALATE
    other = failure_fingerprint(red_tests("t::other"), review_ok())
    assert decide(test_results=bad, failure_fingerprints=[other, other]) is Decision.RETRY


def test_shrinking_the_suite_escalates_instead_of_accepting():
    assert decide(test_results=green_tests(3), best_test_count=5) is Decision.ESCALATE
    assert decide(test_results=green_tests(5), best_test_count=5) is Decision.COMPLETE


def test_acceptance_beats_limits():
    assert decide(iteration_in_run=5, tokens_used=99_999, now=99_999.0) is Decision.COMPLETE


def test_fingerprint_includes_review_findings():
    base = failure_fingerprint(green_tests(), review_ok())
    unmet = {**review_ok(), "acceptance_criteria": [{**CRITERION, "met": False}]}
    insecure = {**review_ok(), "unapproved_high_severity": 2}
    assert (
        len(
            {
                base,
                failure_fingerprint(green_tests(), unmet),
                failure_fingerprint(green_tests(), insecure),
            }
        )
        == 3
    )
    assert failure_fingerprint(green_tests()) == base  # review optional


def test_fingerprint_accepts_spec_style_keys():
    spec = {"failures": [{"test": "t::a", "error_type": "KeyError"}]}
    ours = {"failures": [{"nodeid": "t::a", "error_type": "KeyError"}]}
    assert failure_fingerprint(spec) == failure_fingerprint(ours)


@given(st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=6, unique=True), st.randoms())
def test_fingerprint_is_order_independent(names, rnd):
    shuffled = list(names)
    rnd.shuffle(shuffled)
    assert failure_fingerprint(red_tests(*names)) == failure_fingerprint(red_tests(*shuffled))
