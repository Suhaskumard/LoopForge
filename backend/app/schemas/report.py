import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.plan import _Strict


class ReadmeOutput(_Strict):
    """Documentation Agent output: a README for the generated project, nothing else."""

    content: str = Field(min_length=20, max_length=20_000)


class ReportRequirement(BaseModel):
    req_id: str
    description: str
    req_type: str
    priority: str
    implemented_in: list[str]
    tested_in: list[str]
    verification_status: str
    evidence: str | None


class ReportIteration(BaseModel):
    number: int
    status: str
    tests_total: int
    tests_passed: int
    tests_failed: int
    coverage: float | None
    quality_score: float | None
    decision: str | None
    repair_root_cause: str | None
    repair_files: list[str]


class FinalReport(BaseModel):
    """Everything here is read from stored execution records (spec: evidence over assertion)."""

    task_id: uuid.UUID
    requirement: str
    status: str
    outcome: str
    escalation_reason: str | None
    iterations: list[ReportIteration]
    requirements: list[ReportRequirement]
    acceptance_criteria: list[dict[str, Any]]
    tests: dict[str, Any]
    quality: dict[str, Any]
    files: list[dict[str, str]]
    total_tokens: int
    estimated_cost: float
    approvals: list[dict[str, Any]]
    readme_generated: bool
    generated_at: str
