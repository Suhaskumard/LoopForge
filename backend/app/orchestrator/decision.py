"""Decision Engine (spec §4.7 / §5.3): deterministic loop control. No LLM, no I/O.

Every termination path is safety-relevant, so this module must keep 100% branch coverage.
"""

import hashlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Decision(str, Enum):
    COMPLETE = "complete"
    RETRY = "retry"
    ESCALATE = "escalate"
    STOP = "stop"


@dataclass(frozen=True)
class Limits:
    max_tokens: int
    max_task_seconds: float
    max_attempts_per_failure: int = 2


def failure_fingerprint(tests: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    """Stable id of *what* is failing, independent of order and of messages/line numbers.

    Test failures contribute `test:error_type`; unmet acceptance criteria and open security
    findings contribute too, so a requirement-level failure that repeats is also detected.
    """
    keys = [
        f"{f.get('test', f.get('nodeid', ''))}:{f.get('error_type', '')}" for f in tests["failures"]
    ]
    if review:
        keys += [
            f"criterion:{c['criterion']}" for c in review["acceptance_criteria"] if not c["met"]
        ]
        if review["unapproved_high_severity"]:
            keys.append(f"security:{review['unapproved_high_severity']}")
    return hashlib.sha256("|".join(sorted(keys)).encode()).hexdigest()


def is_accepted(tests: dict[str, Any], review: dict[str, Any]) -> bool:
    return bool(
        tests["total_tests"] > 0
        and tests["failed"] == 0
        and review["critical_issues"] == 0
        and review["unapproved_high_severity"] == 0
        and review.get("unverified_mandatory", 0) == 0
        and all(c["met"] for c in review["acceptance_criteria"])
    )


def evaluate_iteration(state: dict[str, Any], limits: Limits, now: float | None = None) -> Decision:
    """Pick the next action. Order matters: cancel > cheating guard > accept > limits > repeats."""
    if state["status"] == "cancelled":
        return Decision.STOP

    tests, review = state["test_results"], state["review_results"]

    # Repair must never "pass" by deleting tests: the suite may not shrink below its best size.
    if tests["total_tests"] < state.get("best_test_count", 0):
        return Decision.ESCALATE

    if is_accepted(tests, review):
        return Decision.COMPLETE

    if state["iteration_in_run"] >= state["max_iterations"]:
        return Decision.ESCALATE

    if state["tokens_used"] >= limits.max_tokens:
        return Decision.ESCALATE

    clock = time.time() if now is None else now
    if clock - state["started_at"] >= limits.max_task_seconds:
        return Decision.ESCALATE

    fp = failure_fingerprint(tests, review)
    if state["failure_fingerprints"].count(fp) >= limits.max_attempts_per_failure:
        return Decision.ESCALATE  # the same failure keeps recurring despite repairs

    return Decision.RETRY
