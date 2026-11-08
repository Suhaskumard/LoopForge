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
    # Phase 9 (ADR-0016): each switch is on in production (E3) and removable for ablation.
    failure_routing: bool = True  # P1 removes failure-class repair strategies
    targeted_context: bool = True  # P2 sends every file in full again instead of relevant ones
    test_guard: bool = True  # P3 removes the test-weakening check (the test-count guard stays)
    history_retrieval: bool = True  # P4 falls back to "last 3 attempts" instead of similar failures


E3 = LoopConfig()
PRESETS: dict[str, LoopConfig] = {
    "E1": replace(E3, name="E1", max_iterations=1),  # single-shot: generate, test once, stop
    "E2": replace(E3, name="E2", max_iterations=2),  # generate + exactly one correction cycle
    "E3": E3,
    "A1": replace(E3, name="A1", reviewer_enabled=False),
    "A2": replace(E3, name="A2", memory_enabled=False),
    "A3": replace(E3, name="A3", requirement_verification=False),
    "A4": replace(E3, name="A4", adaptive_retry=False),
    # Phase 9: P0 = everything new off (Phase 8 behaviour); P1-P4 = E3 with ONE Phase 9 switch off.
    "P0": replace(
        E3,
        name="P0",
        failure_routing=False,
        targeted_context=False,
        test_guard=False,
        history_retrieval=False,
    ),
    "P1": replace(E3, name="P1", failure_routing=False),
    "P2": replace(E3, name="P2", targeted_context=False),
    "P3": replace(E3, name="P3", test_guard=False),
    "P4": replace(E3, name="P4", history_retrieval=False),
}
