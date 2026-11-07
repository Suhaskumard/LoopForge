"""The Alembic migration must produce exactly the schema the models describe."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.database.models import Base


def _cfg(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.cmd_opts = type("O", (), {"x": [f"url={url}"]})()
    return cfg


def test_migration_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    command.upgrade(_cfg(url), "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"models drifted from migration: {diff}"


def test_migration_downgrade_is_clean(tmp_path):
    url = f"sqlite:///{tmp_path / 'down.db'}"
    command.upgrade(_cfg(url), "head")
    command.downgrade(_cfg(url), "base")
    engine = create_engine(url)
    with engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.exec_driver_sql("select name from sqlite_master where type = 'table'")
        }
    engine.dispose()
    assert tables <= {"alembic_version"}
