"""phase 13: audit_log cannot be TRUNCATEd either (PostgreSQL)

Revision ID: 0009
Revises: 0008

Found by running the suite on a real PostgreSQL: the row-level UPDATE/DELETE triggers of migration 0006 do not
fire for TRUNCATE, so `TRUNCATE audit_log` erased the whole append-only log. A statement-level BEFORE TRUNCATE
trigger closes that hole. SQLite has no TRUNCATE statement, so nothing is needed there.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
            "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
