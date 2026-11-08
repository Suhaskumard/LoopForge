import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskCreate(BaseModel):
    project_id: uuid.UUID
    requirement: str = Field(min_length=1)
    max_iterations: int = Field(default=5, ge=1, le=20)
    acceptance_criteria: list[str] = []
    # Optional per-task budgets; the server's limits are the ceiling (checked in the endpoint).
    token_budget: int | None = Field(default=None, ge=1000)
    max_cost: float | None = Field(default=None, gt=0)
    require_plan_approval: bool = False
    learn_from_task: bool = True  # Phase 16: False keeps this task's repairs out of shared memory
    # Phase 8: start from an existing repository; a zip is uploaded via /tasks/{id}/source.
    source_type: Literal["none", "zip", "git"] = "none"
    git_url: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _source_consistency(self) -> "TaskCreate":
        if self.source_type == "git" and not self.git_url:
            raise ValueError("git_url is required when source_type is 'git'")
        if self.source_type != "git" and self.git_url:
            raise ValueError("git_url is only valid when source_type is 'git'")
        return self


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    requirement: str
    status: str
    max_iterations: int
    current_iteration: int
    acceptance_criteria: list[str]
    token_budget: int | None = None
    max_cost: float | None = None
    require_plan_approval: bool = False
    learn_from_task: bool = True
    source_type: str = "none"
    source_ref: str | None = None
    source_hash: str | None = None
    version: int
    created_at: datetime


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_type: str
    event_data: dict[str, Any]
    created_at: datetime
