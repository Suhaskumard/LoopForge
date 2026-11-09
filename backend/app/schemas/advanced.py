"""Round 12: failure explanations, pipelines and model routing."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.plan import _Strict

MODEL_NAME = r"^[A-Za-z0-9._:/-]{1,80}$"
ROUTABLE_AGENTS = ("Planner", "Builder", "Repair", "Reviewer", "Documentation", "Explainer")


# ---- failure explainer ---------------------------------------------------------------------------


class ExplainOutput(_Strict):
    """What the Explainer agent must return (validated; extra keys are rejected)."""

    summary: str = Field(min_length=10, max_length=600)
    root_causes: list[str] = Field(min_length=1, max_length=5)
    suggested_fix: str = Field(min_length=5, max_length=800)
    retry_note: str = Field(min_length=5, max_length=500)
    confidence: Literal["low", "medium", "high"] = "medium"


class Explanation(BaseModel):
    summary: str
    root_causes: list[str]
    suggested_fix: str
    retry_note: str
    confidence: Literal["low", "medium", "high"]
    source: Literal["ai", "evidence"]  # model-written, or composed from stored facts only
    evidence: list[str]  # the facts it was given
    iteration: int
    created_at: datetime


# ---- pipelines -----------------------------------------------------------------------------------


class StepIn(BaseModel):
    requirement: str = Field(min_length=5, max_length=4000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=30)
    max_iterations: int = Field(default=5, ge=1, le=20)


class PipelineCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    steps: list[StepIn] = Field(min_length=2, max_length=10)


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    position: int
    requirement: str
    acceptance_criteria: list[str]
    max_iterations: int
    task_id: uuid.UUID | None
    status: str
    task_status: str | None = None


class PipelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    steps: list[StepOut] = Field(default_factory=list)


# ---- model routing -------------------------------------------------------------------------------


class ModelStat(BaseModel):
    agent: str
    model: str
    runs: int
    tasks: int
    accepted: int
    accept_rate: float | None
    tokens_per_run: float
    cost_per_run: float


class Recommendation(BaseModel):
    agent: str
    model: str | None  # None = not enough evidence
    reason: str


class RoutingOut(BaseModel):
    routing: dict[str, str]
    stats: list[ModelStat]
    recommendations: list[Recommendation]
    window_days: int


class RoutingIn(BaseModel):
    routing: dict[str, str] = Field(default_factory=dict)
