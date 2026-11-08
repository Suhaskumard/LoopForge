"""phase 18: rate counters, idempotency keys, organization plan

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_counters",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("window_start", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", "key", "route", name="uq_idempotency"),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])
    op.add_column(
        "organizations",
        sa.Column("plan", sa.String(), nullable=False, server_default="default"),
    )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("plan")
    op.drop_table("idempotency_keys")
    op.drop_table("rate_counters")
