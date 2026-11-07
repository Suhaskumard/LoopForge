from typing import Any, TypedDict


class LoopForgeState(TypedDict):
    """Shared state passed between graph nodes (spec §5.1).

    Large files and logs are stored as artifacts and referenced by id, never carried inline.
    `error` is an addition for Phase 2: set when an agent fails, so routing stays deterministic.
    """

    task_id: str
    user_requirement: str
    project_plan: dict[str, Any]
    generated_files: dict[str, str]  # path -> artifact id
    test_results: dict[str, Any]
    review_results: dict[str, Any]
    failure_analysis: str | None
    failure_fingerprints: list[str]  # for repeated-failure detection (Phase 4)
    iteration: int
    max_iterations: int
    tokens_used: int
    started_at: float
    execution_history: list[dict[str, Any]]
    quality_score: float
    status: str
    final_report: dict[str, Any] | None
    error: str | None
    escalate: bool
    # Phase 4 additions (deterministic loop control)
    iteration_in_run: int  # 1-based count of iterations in THIS run; max_iterations is per run
    best_test_count: int  # largest suite seen; the suite may never shrink (anti-cheating guard)
    decision: str | None
    quality: dict[str, Any]  # ruff/bandit report of the current iteration
    failure_report: dict[str, Any]
