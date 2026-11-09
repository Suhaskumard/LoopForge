"""round 12: pipelines, organization model routing

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("model_routing", JSON, nullable=False, server_default="{}")
    )
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','running','paused','completed','failed')", name="ck_pipeline_status"
        ),
    )
    op.create_index("ix_pipelines_org_id", "pipelines", ["org_id"])
    op.create_index("ix_pipelines_project_id", "pipelines", ["project_id"])
    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pipeline_id", sa.Uuid(), sa.ForeignKey("pipelines.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", JSON, nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.UniqueConstraint("pipeline_id", "position", name="uq_pipeline_step_position"),
        sa.CheckConstraint(
            "status IN ('pending','running','accepted','failed')", name="ck_pipeline_step_status"
        ),
    )
    op.create_index("ix_pipeline_steps_pipeline_id", "pipeline_steps", ["pipeline_id"])
    op.create_index("ix_pipeline_steps_task_id", "pipeline_steps", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_steps_task_id", table_name="pipeline_steps")
    op.drop_index("ix_pipeline_steps_pipeline_id", table_name="pipeline_steps")
    op.drop_table("pipeline_steps")
    op.drop_index("ix_pipelines_project_id", table_name="pipelines")
    op.drop_index("ix_pipelines_org_id", table_name="pipelines")
    op.drop_table("pipelines")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("model_routing")
