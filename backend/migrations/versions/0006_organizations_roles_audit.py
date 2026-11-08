"""phase 10: organizations, memberships, roles, org-scoped projects, audit_log, OIDC columns

Revision ID: 0006
Revises: 0005

Data step: every existing user gets a personal organization (they are its admin) and their existing
projects move into it, so nothing becomes unreachable after the upgrade.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("token_quota_month", sa.Integer(), nullable=True),
        sa.Column("max_tasks_month", sa.Integer(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("redact_pii", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('viewer','developer','approver','admin')", name="ck_member_role"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership"),
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("detail", JSON, nullable=False),
        sa.Column("ip", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_org_id", "audit_log", ["org_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    with op.batch_alter_table("users") as batch:
        batch.alter_column("password_hash", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("oidc_issuer", sa.String(), nullable=True))
        batch.add_column(sa.Column("oidc_sub", sa.String(), nullable=True))
        batch.create_unique_constraint("uq_users_oidc", ["oidc_issuer", "oidc_sub"])
    with op.batch_alter_table("approval_requests") as batch:
        batch.add_column(sa.Column("decided_by", sa.Uuid(), nullable=True))
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("org_id", sa.Uuid(), nullable=True))

    # ---- data step: a personal organization per existing user -------------------------------
    bind = op.get_bind()
    users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("email", sa.String()))
    orgs = sa.table(
        "organizations",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("redact_pii", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    members = sa.table(
        "memberships",
        sa.column("id", sa.Uuid()),
        sa.column("org_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("role", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    projects = sa.table("projects", sa.column("user_id", sa.Uuid()), sa.column("org_id", sa.Uuid()))
    now = sa.func.current_timestamp()
    for user_id, email in bind.execute(sa.select(users.c.id, users.c.email)).all():
        org_id = uuid.uuid4()
        bind.execute(
            orgs.insert().values(
                id=org_id,
                name=f"{email.split('@')[0]}'s workspace",
                slug=f"u-{user_id.hex[:12]}",
                redact_pii=False,
                created_at=now,
            )
        )
        bind.execute(
            members.insert().values(
                id=uuid.uuid4(), org_id=org_id, user_id=user_id, role="admin", created_at=now
            )
        )
        bind.execute(projects.update().where(projects.c.user_id == user_id).values(org_id=org_id))

    with op.batch_alter_table("projects") as batch:
        batch.alter_column("org_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_projects_org_id", "organizations", ["org_id"], ["id"])
        batch.create_index("ix_projects_org_id", ["org_id"])

    # ---- append-only audit_log: the database itself refuses UPDATE and DELETE ----------------
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()"
        )
    else:
        for verb in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER audit_log_no_{verb.lower()} BEFORE {verb} ON audit_log "
                "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER audit_log_no_change ON audit_log")
        op.execute("DROP FUNCTION audit_log_immutable()")
    else:
        op.execute("DROP TRIGGER audit_log_no_update")
        op.execute("DROP TRIGGER audit_log_no_delete")
    with op.batch_alter_table("projects") as batch:
        batch.drop_index("ix_projects_org_id")
        batch.drop_constraint("fk_projects_org_id", type_="foreignkey")
        batch.drop_column("org_id")
    with op.batch_alter_table("approval_requests") as batch:
        batch.drop_column("decided_by")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_oidc", type_="unique")
        batch.drop_column("oidc_sub")
        batch.drop_column("oidc_issuer")
        # SSO-only users have no password: give them an unusable one so the column can be NOT NULL again
        batch.alter_column("password_hash", existing_type=sa.String(), nullable=False)
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_org_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_org_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
