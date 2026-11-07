"""Error classifier (4.1): tags failures with their feedback channel (spec §5.4).

execution   - what happened when the code ran (syntax/import/runtime errors, failed tests, timeouts)
quality     - how good the implementation is (Ruff, Bandit, coverage)
requirement - does it fulfil the task (unmet acceptance criteria from the Reviewer)
"""

import re
from typing import Any, Literal

Channel = Literal["execution", "quality", "requirement"]

_ERROR_LINE = re.compile(
    r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b", re.M
)
_BARE_ERROR = re.compile(r"\b([A-Z][A-Za-z]*(?:Error|Exception))\b")
_ASSERT = re.compile(r"^E?\s*>?\s*assert\b|\bAssertionError\b", re.M)


def extract_error_type(message: str, traceback: str) -> str:
    """Best-effort exception class name; stable across line numbers and values."""
    for text in (traceback, message):
        m = _ERROR_LINE.search(text) or _BARE_ERROR.search(text)
        if m:
            return m.group(1).rsplit(".", 1)[-1]
    if _ASSERT.search(traceback) or _ASSERT.search(message):
        return "AssertionError"
    if "exceeded" in message and "killed" in message:
        return "Timeout"
    return "Unknown"


def classify_execution(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in failures:
        error_type = f.get("error_type") or extract_error_type(
            f.get("message", ""), f.get("traceback", "")
        )
        out.append({"channel": "execution", **f, "error_type": error_type})
    return out


def classify_quality(
    ruff: list[dict[str, Any]], bandit_high: list[dict[str, Any]], coverage: float | None
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {"channel": "quality", "tool": "bandit", "severity": "HIGH", **b} for b in bandit_high
    ]
    items += [{"channel": "quality", "tool": "ruff", **r} for r in ruff]
    if coverage is not None and coverage < 60.0:
        items.append(
            {"channel": "quality", "tool": "coverage", "message": f"coverage {coverage:.0f}% < 60%"}
        )
    return items


def classify_requirements(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "channel": "requirement",
            "criterion": c["criterion"],
            "message": c.get("evidence", ""),
        }
        for c in criteria
        if not c["met"]
    ]


def build_failure_report(
    failures: list[dict[str, Any]],
    quality_items: list[dict[str, Any]],
    requirement_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """What the Repair agent sees: all three channels, execution failures first."""
    return {
        "execution": classify_execution(failures),
        "quality": quality_items,
        "requirement": requirement_items,
    }
