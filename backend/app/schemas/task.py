import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    project_id: uuid.UUID
    requirement: str = Field(min_length=1)
    max_iterations: int = Field(default=5, ge=1, le=20)
    acceptance_criteria: list[str] = []


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    requirement: str
    status: str
    max_iterations: int
    current_iteration: int
    acceptance_criteria: list[str]
    version: int
    created_at: datetime


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_type: str
    event_data: dict[str, Any]
    created_at: datetime
