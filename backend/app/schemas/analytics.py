import uuid
from typing import Any

from pydantic import BaseModel


class TaskBrief(BaseModel):
    id: uuid.UUID
    requirement: str
    status: str
    iterations: int
    created_at: str


class OverviewOut(BaseModel):
    """Dashboard KPIs (spec §9.1). `None` means "not computable yet", never a fake zero."""

    tasks_total: int
    tasks_by_status: dict[str, int]
    eligible_finished: int
    completed: int
    task_success_rate: float | None
    average_iterations: float | None
    test_pass_rate: float | None
    tests_executed: int
    tests_passed: int
    average_quality_score: float | None
    average_execution_seconds: float | None
    average_cost: float | None
    total_tokens: int
    total_cost: float
    iteration_efficiency: float | None
    failure_distribution: dict[str, int]
    repair_outcomes: dict[str, dict[str, int]]
    cost_is_estimate: bool = True
    recent_tasks: list[TaskBrief]


class IterationStat(BaseModel):
    number: int
    status: str
    quality_score: float | None
    tests_total: int
    tests_passed: int
    tests_failed: int
    coverage: float | None
    tokens: int
    duration_seconds: float


class TaskAnalyticsOut(BaseModel):
    task_id: uuid.UUID
    status: str
    iterations: list[IterationStat]
    total_tokens: int
    estimated_cost: float
    execution_seconds: float | None
    quality_trend: list[float | None]
    failure_categories: dict[str, int]


class AgentRunStat(BaseModel):
    agent: str
    runs: int
    tokens: int
    duration_seconds: float


class IterationAnalyticsOut(BaseModel):
    iteration_id: uuid.UUID
    number: int
    status: str
    quality_score: float | None
    tests: dict[str, Any]
    agents: list[AgentRunStat]
    total_tokens: int
    duration_seconds: float
    decision: dict[str, Any] | None


class AgentStatOut(BaseModel):
    agent: str
    runs: int
    successes: int
    failures: int
    success_rate: float | None
    average_duration_seconds: float | None
    tokens: int


class AgentStatusOut(AgentStatOut):
    last_status: str | None
    last_run_at: str | None
