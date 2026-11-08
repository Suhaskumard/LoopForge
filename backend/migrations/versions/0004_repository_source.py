"""task source (existing repository input): source_type / source_ref / source_hash

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("source_type", sa.String(), nullable=False, server_default="none"))
        batch.add_column(sa.Column("source_ref", sa.String(), nullable=True))
        batch.add_column(sa.Column("source_hash", sa.String(), nullable=True))
        batch.create_check_constraint("ck_tasks_source_type", "source_type IN ('none','zip','git')")


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("ck_tasks_source_type", type_="check")
        batch.drop_column("source_hash")
        batch.drop_column("source_ref")
        batch.drop_column("source_type")
