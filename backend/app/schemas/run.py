import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    req_id: str
    description: str
    req_type: str
    priority: str
    impl_mapping: list[str]
    test_mapping: list[str]
    verification_status: str
    evidence_ref: str | None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    iteration_id: uuid.UUID
    agent_name: str
    input_summary: str
    output_summary: str
    status: str
    tokens_used: int
    duration_seconds: float
    error_message: str | None
    started_at: datetime


class FileOut(BaseModel):
    path: str
    sha256: str
    iteration: int
    created_at: datetime


class FileContentOut(BaseModel):
    path: str
    sha256: str
    content: str


class PlanOut(BaseModel):
    iteration: int
    plan: dict[str, Any]


class AgentInfo(BaseModel):
    name: str
    role: str
    implemented: bool
    phase: int
    may_not: str


class TestResultOut(BaseModel):
    __test__ = False
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    iteration_id: uuid.UUID
    total_tests: int
    passed: int
    failed: int
    skipped: int
    coverage: float | None
    details: dict[str, Any]
    created_at: datetime


class LogOut(BaseModel):
    name: str
    sha256: str
    content: str


class IterationOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    number: int
    status: str
    quality_score: float | None
    started_at: datetime
    completed_at: datetime | None
    tests: dict[str, Any]
    decision: dict[str, Any] | None
    repair: dict[str, Any] | None


class IterationDetailOut(IterationOut):
    test_results: list[TestResultOut]
    agent_runs: list[AgentRunOut]
    review: dict[str, Any] | None
    quality: dict[str, Any] | None
    files: list[FileOut]


class FileDiffOut(BaseModel):
    path: str
    status: str
    diff: str


class IterationDiffOut(BaseModel):
    iteration: int
    against: int | None
    files: list[FileDiffOut]
