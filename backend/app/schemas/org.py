import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["viewer", "developer", "approver", "admin"]


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class OrgUpdate(BaseModel):
    """PATCH semantics: a field sent as null clears a cap; an omitted field is unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    token_quota_month: int | None = Field(default=None, ge=1)
    max_tasks_month: int | None = Field(default=None, ge=1)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    redact_pii: bool | None = None


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    token_quota_month: int | None
    max_tasks_month: int | None
    retention_days: int | None
    redact_pii: bool
    created_at: datetime


class OrgMembershipOut(BaseModel):
    """An organization the caller belongs to, with the caller's role in it."""

    id: uuid.UUID
    name: str
    slug: str
    role: Role


class MemberAdd(BaseModel):
    email: EmailStr
    role: Role = "developer"


class MemberUpdate(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    role: Role


class UsageOut(BaseModel):
    tokens_used: int
    token_quota_month: int | None
    tokens_remaining: int | None
    tasks_created: int
    max_tasks_month: int | None
    tasks_remaining: int | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    target_type: str
    target_id: str
    detail: dict[str, object]
    ip: str
    created_at: datetime


class DeleteDataRequest(BaseModel):
    confirm: str


class DeleteDataOut(BaseModel):
    deleted_tasks: int


class RetentionOut(BaseModel):
    purged_tasks: int


class InviteCreate(BaseModel):
    email: EmailStr
    role: Role = "developer"


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    role: Role
    expires_at: datetime
    created_at: datetime


class InviteAccept(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class InviteAccepted(BaseModel):
    org_id: uuid.UUID
    role: Role


class MemberQuota(BaseModel):
    token_quota_month: int | None = Field(default=None, ge=0)
    max_tasks_month: int | None = Field(default=None, ge=0)


class QuotaWarning(BaseModel):
    scope: str
    resource: str
    used: int
    cap: int


class MyUsageOut(BaseModel):
    org: UsageOut
    member: UsageOut
    warnings: list[QuotaWarning]
