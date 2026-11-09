"""round 9: task chains, re-runs and A/B variants, code comments, regression watches

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("rerun_of", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("experiment", sa.String(), nullable=True))
        batch.add_column(sa.Column("model_overrides", JSON, nullable=False, server_default="{}"))
        batch.drop_constraint("ck_tasks_source_type", type_="check")
        batch.create_check_constraint(
            "ck_tasks_source_type", "source_type IN ('none','zip','git','task')"
        )
    op.create_index("ix_tasks_rerun_of", "tasks", ["rerun_of"])
    op.create_index("ix_tasks_experiment", "tasks", ["experiment"])

    op.create_table(
        "code_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("iteration_number", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_code_comments_task_id", "code_comments", ["task_id"])

    op.create_table(
        "regression_watches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_task_id", sa.Uuid(), nullable=True),
        sa.Column("last_result", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("interval_hours IN (24, 168)", name="ck_regression_interval"),
    )
    op.create_index("ix_regression_watches_org_id", "regression_watches", ["org_id"])
    op.create_index("ix_regression_watches_next_run_at", "regression_watches", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_regression_watches_next_run_at", table_name="regression_watches")
    op.drop_index("ix_regression_watches_org_id", table_name="regression_watches")
    op.drop_table("regression_watches")
    op.drop_index("ix_code_comments_task_id", table_name="code_comments")
    op.drop_table("code_comments")
    op.drop_index("ix_tasks_experiment", table_name="tasks")
    op.drop_index("ix_tasks_rerun_of", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_source_type", type_="check")
        batch.create_check_constraint("ck_tasks_source_type", "source_type IN ('none','zip','git')")
        batch.drop_column("model_overrides")
        batch.drop_column("experiment")
        batch.drop_column("rerun_of")
