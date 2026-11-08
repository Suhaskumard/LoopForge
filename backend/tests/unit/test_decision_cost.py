"""Phase 6: the estimated-cost ceiling in the Decision Engine (all branches)."""

from app.orchestrator.decision import Decision, Limits, evaluate_iteration
from tests.unit.test_decision import red_tests, state


def test_cost_ceiling_escalates_when_spend_reaches_the_cap():
    capped = Limits(
        max_tokens=1_000_000, max_task_seconds=900, max_cost=0.10, cost_per_1k_tokens=0.01
    )
    # 10_000 tokens x $0.01 per 1k = $0.10 -> exactly at the cap
    s = state(test_results=red_tests(), tokens_used=10_000)
    assert evaluate_iteration(s, capped, now=1001.0) is Decision.ESCALATE
    s = state(test_results=red_tests(), tokens_used=9_999)
    assert evaluate_iteration(s, capped, now=1001.0) is Decision.RETRY


def test_no_cost_cap_means_cost_never_escalates():
    uncapped = Limits(max_tokens=10**9, max_task_seconds=900, cost_per_1k_tokens=100.0)
    s = state(test_results=red_tests(), tokens_used=5_000_000)
    assert evaluate_iteration(s, uncapped, now=1001.0) is Decision.RETRY


def test_accepted_work_is_accepted_even_over_the_cost_cap():
    capped = Limits(max_tokens=10**9, max_task_seconds=900, max_cost=0.01, cost_per_1k_tokens=1.0)
    assert evaluate_iteration(state(tokens_used=50_000), capped, now=1001.0) is Decision.COMPLETE
