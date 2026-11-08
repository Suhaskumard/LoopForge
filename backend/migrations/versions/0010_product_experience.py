"""phase 15: email verification, invitations, session metadata, notifications, member quotas

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users", sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("tasks", sa.Column("created_by", sa.Uuid(), nullable=True))
    op.create_index("ix_tasks_created_by", "tasks", ["created_by"])
    op.add_column("memberships", sa.Column("token_quota_month", sa.Integer(), nullable=True))
    op.add_column("memberships", sa.Column("max_tasks_month", sa.Integer(), nullable=True))
    op.add_column(
        "refresh_tokens", sa.Column("user_agent", sa.String(), nullable=False, server_default="")
    )
    op.add_column("refresh_tokens", sa.Column("ip", sa.String(), nullable=False, server_default=""))
    op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(), nullable=True))

    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("purpose IN ('verify','reset')", name="ck_email_token_purpose"),
    )
    op.create_index("ix_email_tokens_user_id", "email_tokens", ["user_id"])

    op.create_table(
        "org_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('viewer','developer','approver','admin')", name="ck_invite_role"
        ),
    )
    op.create_index("ix_org_invites_org_id", "org_invites", ["org_id"])
    op.create_index("ix_org_invites_email", "org_invites", ["email"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("detail", JSON, nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"])

    op.create_table(
        "approval_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "approval_id", sa.Uuid(), sa.ForeignKey("approval_requests.id"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_approval_comments_approval_id", "approval_comments", ["approval_id"])


def downgrade() -> None:
    op.drop_index("ix_approval_comments_approval_id", table_name="approval_comments")
    op.drop_table("approval_comments")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_org_invites_email", table_name="org_invites")
    op.drop_index("ix_org_invites_org_id", table_name="org_invites")
    op.drop_table("org_invites")
    op.drop_index("ix_email_tokens_user_id", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_tasks_created_by", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("created_by")
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.drop_column("last_used_at")
        batch.drop_column("ip")
        batch.drop_column("user_agent")
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("max_tasks_month")
        batch.drop_column("token_quota_month")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("notify_email")
        batch.drop_column("email_verified_at")
