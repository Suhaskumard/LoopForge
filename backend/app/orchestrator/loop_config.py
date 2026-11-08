"""Experiment configurations (spec 12.2 / 12.6) expressed as switches on the SAME loop.

E1-E3 only change the iteration budget; A1-A4 each remove one component. Nothing is forked, so
a measured difference can only come from the switch (and the production defaults are `E3`).
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class LoopConfig:
    name: str = "E3"
    max_iterations: int | None = None  # None = use the task's own limit
    reviewer_enabled: bool = True  # A1 removes the independent LLM Reviewer
    memory_enabled: bool = True  # A2 removes retained failure context in the Repair prompt
    requirement_verification: bool = True  # A3 stops requiring mandatory requirements be verified
    adaptive_retry: bool = True  # A4 removes failure-fingerprint escalation (retry blindly)
    approvals_enabled: bool = True  # benchmarks run unattended


E3 = LoopConfig()
PRESETS: dict[str, LoopConfig] = {
    "E1": replace(E3, name="E1", max_iterations=1),  # single-shot: generate, test once, stop
    "E2": replace(E3, name="E2", max_iterations=2),  # generate + exactly one correction cycle
    "E3": E3,
    "A1": replace(E3, name="A1", reviewer_enabled=False),
    "A2": replace(E3, name="A2", memory_enabled=False),
    "A3": replace(E3, name="A3", requirement_verification=False),
    "A4": replace(E3, name="A4", adaptive_retry=False),
}
