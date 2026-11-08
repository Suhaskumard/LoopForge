"""phase 9: agent_runs.model, repair_history.failure_class / fingerprint

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("model", sa.String(), nullable=True))
    with op.batch_alter_table("repair_history") as batch:
        batch.add_column(sa.Column("failure_class", sa.String(), nullable=False, server_default=""))
        batch.add_column(sa.Column("fingerprint", sa.String(), nullable=True))
        batch.create_index("ix_repair_history_fingerprint", ["fingerprint"])


def downgrade() -> None:
    with op.batch_alter_table("repair_history") as batch:
        batch.drop_index("ix_repair_history_fingerprint")
        batch.drop_column("fingerprint")
        batch.drop_column("failure_class")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("model")
