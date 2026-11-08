import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublishCreate(BaseModel):
    repo: str = Field(min_length=3, max_length=201, description="owner/name")
    base_branch: str = Field(default="main", min_length=1, max_length=100)


class PublishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    repo: str
    base_branch: str
    branch: str
    status: str
    requested_by: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    pr_url: str | None
    ci_state: str | None
    error: str
    created_at: datetime


class GithubTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)


class GithubStatusOut(BaseModel):
    configured: bool


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["viewer", "developer", "approver"] = "developer"
    expires_days: int | None = Field(default=None, ge=1, le=365)


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    prefix: str
    scope: str
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class TokenCreated(TokenOut):
    token: str  # shown exactly once


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(default_factory=list)
    format: Literal["json", "slack"] = "json"


class WebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    url: str
    events: list[str]
    format: str
    active: bool
    created_at: datetime


class WebhookCreated(WebhookOut):
    secret: str  # shown exactly once


class WebhookRotated(BaseModel):
    secret: str  # the new signing secret, shown exactly once
    overlap_hours: int  # until then deliveries are signed with the old secret as well


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event: str
    status: str
    attempts: int
    response_status: int | None
    last_error: str
    created_at: datetime
