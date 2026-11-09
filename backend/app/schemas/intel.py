"""Round 9: forecasts, code comments, regression watches, A/B experiments."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MODEL_NAME = r"^[A-Za-z0-9._:/-]{1,80}$"


class ForecastBand(BaseModel):
    p50: float
    p90: float


class ForecastOut(BaseModel):
    basis: int  # finished tasks the numbers come from
    scope: Literal["similar", "language", "organization", "none"]
    accept_rate: float | None
    tokens: ForecastBand | None
    cost: ForecastBand | None
    iterations: ForecastBand | None
    seconds: ForecastBand | None


class CodeCommentCreate(BaseModel):
    file_path: str = Field(default="", max_length=300)
    line: int | None = Field(default=None, ge=1)
    body: str = Field(min_length=1, max_length=2000)
    iteration_number: int | None = Field(default=None, ge=0)


class CodeCommentUpdate(BaseModel):
    resolved: bool


class CodeCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    iteration_number: int | None
    user_id: uuid.UUID
    author: str = ""
    file_path: str
    line: int | None
    body: str
    resolved: bool
    created_at: datetime


class WatchIn(BaseModel):
    interval_hours: Literal[24, 168] = 168
    active: bool = True


class WatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    task_id: uuid.UUID
    interval_hours: int
    next_run_at: datetime
    last_run_task_id: uuid.UUID | None
    last_result: str
    active: bool


class RerunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    created_at: datetime
    experiment: str | None


class WatchStatus(BaseModel):
    watch: WatchOut | None
    reruns: list[RerunOut]


class ExperimentCreate(BaseModel):
    agent: Literal["Planner", "Builder", "Repair", "Reviewer", "Documentation"]
    model_a: str = Field(pattern=MODEL_NAME)
    model_b: str = Field(pattern=MODEL_NAME)


class VariantOut(BaseModel):
    task_id: uuid.UUID
    status: str
    model_overrides: dict[str, str]
    iterations: int
    tokens: int
    cost: float
    quality: float | None
    seconds: float | None
    rerun_of: uuid.UUID | None


class ExperimentOut(BaseModel):
    experiment: str
    variants: list[VariantOut]
