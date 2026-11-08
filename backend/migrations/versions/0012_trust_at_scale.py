"""phase 17: webhook secret rotation + encryption at rest

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_endpoints", sa.Column("previous_secret", sa.String(), nullable=True))
    op.add_column("webhook_endpoints", sa.Column("rotated_at", sa.DateTime(), nullable=True))
    # identity: SCIM lifecycle, TOTP second factor, membership source, per-org MFA policy
    op.add_column(
        "users", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("users", sa.Column("totp_secret_enc", sa.String(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.Integer(), nullable=True))
    op.add_column(
        "users", sa.Column("recovery_codes", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "memberships",
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
    )
    op.add_column(
        "organizations",
        sa.Column("require_mfa", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "scim_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_scim_tokens_org_id", "scim_tokens", ["org_id"])
    op.create_table(
        "scim_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_scim_identity"),
    )
    op.create_index("ix_scim_identities_org_id", "scim_identities", ["org_id"])
    op.create_index("ix_scim_identities_user_id", "scim_identities", ["user_id"])
    # Existing plaintext secrets are encrypted in place with the active key (idempotent: v2:
    # values are skipped). `python -m app.cli keys rotate` does the same for later key changes.
    from app.utils.security import encrypt_secret

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, secret FROM webhook_endpoints")).fetchall()
    for row_id, secret in rows:
        if not str(secret).startswith("v2:"):
            bind.execute(
                sa.text("UPDATE webhook_endpoints SET secret = :s WHERE id = :i"),
                {"s": encrypt_secret(str(secret)), "i": row_id},
            )


def downgrade() -> None:
    # Secrets stay encrypted (a downgrade must not write key material back in the clear); after a
    # downgrade the endpoints must be re-created.
    op.drop_table("scim_identities")
    op.drop_table("scim_tokens")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("require_mfa")
    with op.batch_alter_table("memberships") as batch:
        batch.drop_column("source")
    with op.batch_alter_table("users") as batch:
        for col in (
            "recovery_codes", "totp_last_step", "totp_enabled_at", "totp_secret_enc",
            "active",
        ):  # fmt: skip
            batch.drop_column(col)
    with op.batch_alter_table("webhook_endpoints") as batch:
        batch.drop_column("rotated_at")
        batch.drop_column("previous_secret")
