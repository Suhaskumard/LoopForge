"""Migration 0006 on a database that already holds Phase 9 data: nothing becomes unreachable."""

import uuid
from datetime import datetime

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.integration.test_migrations import _cfg


def test_existing_users_and_projects_move_into_personal_organizations(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(_cfg(url), "0005")
    engine = create_engine(url)
    user_id, project_id, now = uuid.uuid4().hex, uuid.uuid4().hex, datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, token_version, created_at) "
                "VALUES (:id, 'old@example.com', 'x', 0, :now)"
            ),
            {"id": user_id, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, user_id, name, description, language, version, created_at) "
                "VALUES (:id, :uid, 'legacy', '', 'python', 1, :now)"
            ),
            {"id": project_id, "uid": user_id, "now": now},
        )
    command.upgrade(_cfg(url), "head")
    with engine.connect() as conn:
        org = conn.execute(
            text(
                "SELECT m.role, o.slug, p.org_id = o.id FROM memberships m "
                "JOIN organizations o ON o.id = m.org_id "
                "JOIN projects p ON p.id = :pid WHERE m.user_id = :uid"
            ),
            {"pid": project_id, "uid": user_id},
        ).one()
        assert org[0] == "admin" and org[1].startswith("u-") and org[2] == 1
        assert conn.execute(text("SELECT count(*) FROM organizations")).scalar() == 1

    with engine.begin() as conn:  # a committed row to try to tamper with
        conn.execute(
            text(
                "INSERT INTO audit_log "
                "(id, action, target_type, target_id, detail, ip, created_at) "
                "VALUES ('a', 'x', '', '', '{}', '', :now)"
            ),
            {"now": now},
        )
    for statement in ("UPDATE audit_log SET action = 'y'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError):  # the migration installs the append-only triggers too
            with engine.begin() as conn:
                conn.execute(text(statement))

    command.downgrade(_cfg(url), "0005")  # and it can be undone
    with engine.connect() as conn:
        tables = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        assert not {"organizations", "memberships", "audit_log"} & tables
        assert conn.execute(text("SELECT count(*) FROM projects")).scalar() == 1
    engine.dispose()
