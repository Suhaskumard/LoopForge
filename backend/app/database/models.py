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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    password_hash: Mapped[str] = mapped_column(String)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
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
