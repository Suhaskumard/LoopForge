import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import DDL

JsonType = JSON().with_variant(JSONB(), "postgresql")  # type: ignore[no-untyped-call]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # None: SSO-only user
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    oidc_issuer: Mapped[str | None] = mapped_column(String, nullable=True)  # Phase 10 SSO
    oidc_sub: Mapped[str | None] = mapped_column(String, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)  # Phase 15
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)  # Phase 15 preference
    # Phase 17: SCIM-managed lifecycle and TOTP second factor
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    totp_secret_enc: Mapped[str | None] = mapped_column(String, nullable=True)  # keyring-encrypted
    totp_enabled_at: Mapped[datetime | None] = mapped_column(nullable=True)  # None = not enrolled
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # replay guard
    recovery_codes: Mapped[list[Any]] = mapped_column(JsonType, default=list)  # sha256 hashes
    created_at: Mapped[datetime] = mapped_column(default=_now)
    __table_args__ = (UniqueConstraint("oidc_issuer", "oidc_sub", name="uq_users_oidc"),)
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


ROLES = ("viewer", "developer", "approver", "admin")  # ascending privilege (Phase 10, ADR-0017)


class Organization(Base):
    """Tenant boundary. Every project (and so every task, report, event) belongs to exactly one."""

    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    token_quota_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = no cap
    max_tasks_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = keep
    redact_pii: Mapped[bool] = mapped_column(Boolean, default=False)
    require_mfa: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )  # Ph. 17
    plan: Mapped[str] = mapped_column(String, default="default", server_default="default")  # Ph. 18
    # Round 12: organization-wide {agent_name: model}; a task's own override still wins.
    model_routing: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_membership"),
        CheckConstraint("role IN ('viewer','developer','approver','admin')", name="ck_member_role"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String, default="developer")
    token_quota_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Phase 15
    max_tasks_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Phase 17: who manages this membership. Only 'sso' / 'scim' rows are changed by the IdP.
    source: Mapped[str] = mapped_column(String, default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    org: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class AuditLog(Base):
    """Append-only, org-level record of who did what (DB triggers reject UPDATE and DELETE)."""

    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str] = mapped_column(String, default="")
    target_id: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    ip: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)  # creator
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String, default="python")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": version}
    created_at: Mapped[datetime] = mapped_column(default=_now)
    user: Mapped[User] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PLANNING','GENERATING','EXECUTING','TESTING',"
            "'REVIEWING','REPAIRING','AWAITING_APPROVAL','COMPLETED','FAILED','ESCALATED',"
            "'CANCELLED')",
            name="ck_tasks_status",
        ),
        CheckConstraint("max_iterations >= 1", name="ck_tasks_max_iterations"),
        CheckConstraint("source_type IN ('none','zip','git','task')", name="ck_tasks_source_type"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    max_iterations: Mapped[int] = mapped_column(Integer, default=5)
    current_iteration: Mapped[int] = mapped_column(Integer, default=0)
    acceptance_criteria: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    # Phase 6: per-task budgets (None = server default) and opt-in human review of the plan.
    token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    require_plan_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Phase 8: optional starting repository (none | zip | git). source_hash is set once the seed
    # has been imported and written to iteration 0.
    source_type: Mapped[str] = mapped_column(String, default="none", server_default="none")
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)  # Ph.15
    # Phase 16: False = repairs from this task are never offered as hints to other tasks.
    learn_from_task: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    # Round 9: re-runs (regression watch) and A/B variants point at the task they repeat;
    # variants of one A/B test share `experiment`; `model_overrides` = {agent_name: model}.
    rerun_of: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    experiment: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    model_overrides: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": version}
    created_at: Mapped[datetime] = mapped_column(default=_now)
    project: Mapped[Project] = relationship(back_populates="tasks")
    iterations: Mapped[list["Iteration"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class Iteration(Base):
    __tablename__ = "iterations"
    __table_args__ = (UniqueConstraint("task_id", "iteration_number", name="uq_iteration_seq"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    iteration_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="running")
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    started_at: Mapped[datetime] = mapped_column(default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    task: Mapped[Task] = relationship(back_populates="iterations")
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="iteration", cascade="all, delete-orphan"
    )
    test_results: Mapped[list["TestResult"]] = relationship(
        back_populates="iteration", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="iteration", cascade="all, delete-orphan"
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    iteration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("iterations.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Phase 9: which model served it
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="success")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=_now)
    iteration: Mapped[Iteration] = relationship(back_populates="agent_runs")


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False  # not a pytest class
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    iteration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("iterations.id"), index=True)
    total_tests: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    iteration: Mapped[Iteration] = relationship(back_populates="test_results")


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    iteration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("iterations.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String)
    file_name: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    iteration: Mapped[Iteration] = relationship(back_populates="artifacts")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    event_type: Mapped[str] = mapped_column(String)
    event_data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    task: Mapped[Task] = relationship(back_populates="audit_events")


class Requirement(Base):
    """Addendum 16.1: requirement-to-code traceability record."""

    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("task_id", "req_id", name="uq_requirement_per_task"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    req_id: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    req_type: Mapped[str] = mapped_column(String, default="functional")
    priority: Mapped[str] = mapped_column(String, default="medium")
    impl_mapping: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    test_mapping: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    verification_status: Mapped[str] = mapped_column(String, default="pending")
    evidence_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    task: Mapped[Task] = relationship(back_populates="requirements")


class RepairHistory(Base):
    """Addendum 16.2: persistent record of repair attempts."""

    __tablename__ = "repair_history"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    iteration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("iterations.id"), nullable=True
    )
    original_failure: Mapped[str] = mapped_column(Text, default="")
    failure_category: Mapped[str] = mapped_column(String, default="")
    failure_class: Mapped[str] = mapped_column(String, default="")  # Phase 9: syntax/import/...
    fingerprint: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # Phase 9
    root_cause: Mapped[str] = mapped_column(Text, default="")
    proposed_fix: Mapped[str] = mapped_column(Text, default="")
    files_modified: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    tests_executed: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    outcome: Mapped[str] = mapped_column(String, default="")
    regression_status: Mapped[str] = mapped_column(String, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class RefreshToken(Base):
    """Rotating refresh token; only a SHA-256 hash is stored. family_id groups a rotation chain."""

    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    # Phase 15: session metadata shown on the sessions page
    user_agent: Mapped[str] = mapped_column(String, default="")
    ip: Mapped[str] = mapped_column(String, default="")
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class EmailToken(Base):
    """Single-use token mailed to a user (verify | reset). Only a SHA-256 hash is stored."""

    __tablename__ = "email_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('verify','reset')", name="ck_email_token_purpose"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OrgInvite(Base):
    """An emailed invitation to join an organization with a role (Phase 15)."""

    __tablename__ = "org_invites"
    __table_args__ = (
        CheckConstraint("role IN ('viewer','developer','approver','admin')", name="ck_invite_role"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="developer")
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Notification(Base):
    """In-app notification for one user (Phase 15)."""

    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read_at"),
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),
    )


class ApprovalComment(Base):
    """A reviewer's inline comment on an approval's diff (Phase 15)."""

    __tablename__ = "approval_comments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    file_path: Mapped[str] = mapped_column(String, default="")
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class CodeComment(Base):
    """A person's note on a line of generated code (Round 9). Unresolved notes are given to the
    Repair agent as hints (wrapped as untrusted data, like every other input)."""

    __tablename__ = "code_comments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    iteration_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    file_path: Mapped[str] = mapped_column(String, default="")
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class RegressionWatch(Base):
    """Re-run an accepted task on a schedule and alert when it stops passing (Round 9)."""

    __tablename__ = "regression_watches"
    __table_args__ = (
        CheckConstraint("interval_hours IN (24, 168)", name="ck_regression_interval"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    interval_hours: Mapped[int] = mapped_column(Integer, default=168)
    next_run_at: Mapped[datetime] = mapped_column(index=True)
    last_run_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    last_result: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Pipeline(Base):
    """Round 12: ordered steps that run one after another; each starts from the previous step's
    accepted code (a task chain), automatically."""

    __tablename__ = "pipelines"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','running','paused','completed','failed')", name="ck_pipeline_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan", order_by="PipelineStep.position"
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "position", name="uq_pipeline_step_position"),
        CheckConstraint(
            "status IN ('pending','running','accepted','failed')", name="ck_pipeline_step_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    requirement: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    max_iterations: Mapped[int] = mapped_column(Integer, default=5)
    # the task running this step; no FK so deleting a task never trips over a pipeline
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    pipeline: Mapped[Pipeline] = relationship(back_populates="steps")


class RateCounter(Base):
    """Fixed-window request counter (Phase 18): one row per (key, window), shared by processes."""

    __tablename__ = "rate_counters"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    window_start: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class IdempotencyKey(Base):
    """A client-supplied key that makes a POST safe to retry (Phase 18). Unique per scope+route."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key", "route", name="uq_idempotency"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String)  # hash of the caller's credential + org
    key: Mapped[str] = mapped_column(String)
    route: Mapped[str] = mapped_column(String)  # METHOD + route template
    request_hash: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="in_progress")  # in_progress | done
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)


class LoginAttempt(Base):
    """Failed-login log used for rate limiting; DB-backed so it is shared across workers."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_key_time", "key", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ApprovalRequest(Base):
    """A human decision the loop is waiting for (spec 13.2 "human approval gate").

    kind: `plan` (task opted in to plan review) | `large_repair` (a repair touching many files).
    `resume_status` is the task status to return to once approved.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected')", name="ck_approval_status"),
        CheckConstraint("kind IN ('plan','large_repair')", name="ck_approval_kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    iteration_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    resume_status: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # Phase 10


class RunLease(Base):
    """Cross-process lock: the single owner currently driving a task's loop (Phase 7, ADR-0014).

    Held by a heartbeat; an expired lease means the owner died and the task may be taken over.
    """

    __tablename__ = "run_leases"
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    owner: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column()
    acquired_at: Mapped[datetime] = mapped_column(default=_now)


class Job(Base):
    """A unit of work for the worker service: start or resume one task's run."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('start','resume')", name="ck_jobs_kind"),
        CheckConstraint("status IN ('queued','running','done','failed')", name="ck_jobs_status"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Phase 12 tracing
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    claimed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class OrgIntegration(Base):
    """Per-organization credential for a git provider (Phase 11). The token is stored encrypted."""

    __tablename__ = "org_integrations"
    __table_args__ = (UniqueConstraint("org_id", "provider", name="uq_org_integration"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String, default="github")
    token_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class PublishRequest(Base):
    """A request to open a pull request with a task's result. Nothing is pushed until `approved`."""

    __tablename__ = "publish_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','approved','rejected','pushed','failed')",
            name="ck_publish_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String, default="github")
    repo: Mapped[str] = mapped_column(String)  # owner/name
    base_branch: Mapped[str] = mapped_column(String, default="main")
    branch: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="requested")
    requested_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    ci_state: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ScimToken(Base):
    """Bearer credential for an identity provider's SCIM client (Phase 17). Bound to one org."""

    __tablename__ = "scim_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    prefix: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ScimIdentity(Base):
    """A user as provisioned into ONE org by that org's identity provider (Phase 17).

    `active` is per organization: deprovisioning removes the user's membership of this org only,
    never their account or other organizations. The row stays so the IdP can still GET the user.
    """

    __tablename__ = "scim_identities"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_scim_identity"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ApiToken(Base):
    """Scoped automation credential. Only the SHA-256 of the secret is stored."""

    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("scope IN ('viewer','developer','approver')", name="ck_api_token_scope"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    prefix: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    scope: Mapped[str] = mapped_column(String, default="developer")
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (CheckConstraint("format IN ('json','slack')", name="ck_webhook_format"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    url: Mapped[str] = mapped_column(String)
    secret: Mapped[str] = mapped_column(String)  # signing key, encrypted at rest (shown once)
    previous_secret: Mapped[str | None] = mapped_column(String, nullable=True)  # rotation overlap
    rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    events: Mapped[list[Any]] = mapped_column(JsonType, default=list)  # [] = all events
    format: Mapped[str] = mapped_column(String, default="json")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','delivered','failed')", name="ck_webhook_delivery_status"
        ),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id"), index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    event: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(default=_now)
    last_error: Mapped[str] = mapped_column(Text, default="")
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


# ---- audit_log is append-only: the database refuses UPDATE and DELETE (Phase 10, ADR-0017) ------
# Installed whenever the table is created (create_all in tests/dev and migration 0006 both end up
# with the same triggers), so the guarantee does not depend on how the schema was built.
def _ddl(sql: str) -> DDL:
    return DDL(sql)  # type: ignore[no-untyped-call]


def _install_audit_triggers() -> None:
    table = AuditLog.__table__
    for verb in ("UPDATE", "DELETE"):
        event.listen(
            table,
            "after_create",
            _ddl(
                f"CREATE TRIGGER audit_log_no_{verb.lower()} BEFORE {verb} ON audit_log "
                "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
            ).execute_if(dialect="sqlite"),
        )
    event.listen(
        table,
        "after_create",
        _ddl(
            "CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql"
        ).execute_if(dialect="postgresql"),
    )
    event.listen(
        table,
        "after_create",
        _ddl(
            "CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()"
        ).execute_if(dialect="postgresql"),
    )
    # Row triggers do not fire for TRUNCATE (found on a real PostgreSQL in Phase 13): guard it
    # separately.
    event.listen(
        table,
        "after_create",
        _ddl(
            "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
            "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()"
        ).execute_if(dialect="postgresql"),
    )


_install_audit_triggers()
