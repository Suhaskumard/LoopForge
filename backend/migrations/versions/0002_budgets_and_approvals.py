"""per-task budgets, plan-approval opt-in, approval requests, AWAITING_APPROVAL status

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OLD = ("'PENDING','PLANNING','GENERATING','EXECUTING','TESTING','REVIEWING','REPAIRING',"
       "'COMPLETED','FAILED','ESCALATED','CANCELLED'")
NEW = ("'PENDING','PLANNING','GENERATING','EXECUTING','TESTING','REVIEWING','REPAIRING',"
       "'AWAITING_APPROVAL','COMPLETED','FAILED','ESCALATED','CANCELLED'")


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("token_budget", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_cost", sa.Float(), nullable=True))
        batch.add_column(sa.Column("require_plan_approval", sa.Boolean(),
                                   nullable=False, server_default=sa.false()))
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint("ck_tasks_status", f"status IN ({NEW})")
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("iteration_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("resume_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending','approved','rejected')", name="ck_approval_status"),
        sa.CheckConstraint("kind IN ('plan','large_repair')", name="ck_approval_kind"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_requests_task_id"), "approval_requests", ["task_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_approval_requests_task_id"), table_name="approval_requests")
    op.drop_table("approval_requests")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_status", type_="check")
        batch.create_check_constraint("ck_tasks_status", f"status IN ({OLD})")
        batch.drop_column("require_plan_approval")
        batch.drop_column("max_cost")
        batch.drop_column("token_budget")
