# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: scripts/backup.sh and scripts/restore.sh run for real against a PostgreSQL container.

Needs the throwaway database from `docker-compose.test.yml` and its container name in PG_CONTAINER (set by
scripts/test_postgres.sh). `pg_dump`/`pg_restore` run INSIDE the container, so nothing has to be installed on the host.
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL

ROOT = Path(__file__).resolve().parents[3]
PG_CONTAINER = os.environ.get("PG_CONTAINER", "")


def _find_bash() -> str | None:
    """A bash that sees the same filesystem and Docker as this process (Git Bash on Windows, not WSL)."""
    if os.environ.get("BASH_EXE"):
        return os.environ["BASH_EXE"]
    git = shutil.which("git")
    if git:  # <git>/cmd/git.exe -> <git>/bin/bash.exe
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    found = shutil.which("bash")
    return None if found and "system32" in found.lower() else found


BASH = _find_bash()

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not (TEST_DATABASE_URL or "").startswith("postgresql") or not PG_CONTAINER,
        reason="needs a real PostgreSQL container (PG_CONTAINER) - run scripts/test_postgres.sh",
    ),
    pytest.mark.skipif(
        BASH is None or shutil.which("openssl") is None,
        reason="needs bash and openssl",
    ),
]


def _bash(
    script: str, *args: str, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess:
    full = {**os.environ, **env}
    return subprocess.run(
        [BASH, (ROOT / "scripts" / script).as_posix(), *args], capture_output=True, text=True, env=full, timeout=300, check=check
    )  # fmt: skip


@pytest.fixture
def database():
    name = f"lf_bk_{uuid.uuid4().hex[:10]}"
    base = make_url(TEST_DATABASE_URL)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE notes (id int primary key, body text)"))
        conn.execute(text("INSERT INTO notes VALUES (1, 'alpha'), (2, 'beta'), (3, 'γ unicode')"))
    yield (
        name,
        url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg", "postgresql+psycopg"
        ),
        engine,
    )
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _rows(engine):
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT id, body FROM notes ORDER BY id"))]


def _env(url: str, workspaces: Path, **extra: str) -> dict[str, str]:
    return {
        "DATABASE_URL": url,
        "WORKSPACE_ROOT": workspaces.as_posix(),
        "PG_CONTAINER": PG_CONTAINER,
        **extra,
    }


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces"
    (ws / "task-1" / "iter_1").mkdir(parents=True)
    (ws / "task-1" / "iter_1" / "app.py").write_text("x = 1\n")
    return ws


def test_backup_then_restore_brings_back_the_database_and_the_workspaces(database, tmp_path):
    name, url, engine = database
    ws = _make_workspace(tmp_path)
    out = tmp_path / "backup"
    _bash("backup.sh", out.as_posix(), env=_env(url, ws))
    assert (out / "database.dump").stat().st_size > 0 and (out / "manifest.sha256").exists()

    with engine.begin() as conn:  # the disaster
        conn.execute(text("DROP TABLE notes"))
    shutil.rmtree(ws)
    _bash("restore.sh", out.as_posix(), "--yes", env=_env(url, ws))

    assert _rows(engine) == [(1, "alpha"), (2, "beta"), (3, "γ unicode")]
    assert (ws / "task-1" / "iter_1" / "app.py").read_text() == "x = 1\n"


def test_restore_refuses_to_run_without_yes_and_refuses_a_corrupt_backup(database, tmp_path):
    name, url, engine = database
    ws = _make_workspace(tmp_path)
    out = tmp_path / "backup"
    _bash("backup.sh", out.as_posix(), env=_env(url, ws))
    assert _bash("restore.sh", out.as_posix(), env=_env(url, ws), check=False).returncode == 2
    with (out / "database.dump").open("r+b") as f:
        f.seek(40)
        f.write(b"\x00\xff\x00\xff")
    bad = _bash("restore.sh", out.as_posix(), "--yes", env=_env(url, ws), check=False)
    assert bad.returncode == 3 and "corrupt" in bad.stdout + bad.stderr
    assert _rows(engine) == [(1, "alpha"), (2, "beta"), (3, "γ unicode")]  # nothing was touched


def test_an_encrypted_backup_hides_the_data_and_needs_the_right_passphrase(database, tmp_path):
    name, url, engine = database
    ws = _make_workspace(tmp_path)
    secret, wrong = tmp_path / "pass.txt", tmp_path / "wrong.txt"
    secret.write_text("correct horse battery staple\n")
    wrong.write_text("tr0ub4dor&3\n")
    out = tmp_path / "backup"
    _bash("backup.sh", out.as_posix(), env=_env(url, ws, BACKUP_PASSPHRASE_FILE=secret.as_posix()))
    names = {p.name for p in out.iterdir()}
    assert names == {
        "database.dump.enc",
        "workspaces.tar.gz.enc",
        "manifest.sha256",
    }  # no plaintext copy left
    blob = b"".join(p.read_bytes() for p in out.iterdir())
    assert b"alpha" not in blob and b"PGDMP" not in blob and b"app.py" not in blob

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE notes"))
    no_key = _bash("restore.sh", out.as_posix(), "--yes", env=_env(url, ws), check=False)
    assert no_key.returncode == 6 and "encrypted" in no_key.stdout + no_key.stderr
    bad_key = _bash(
        "restore.sh",
        out.as_posix(),
        "--yes",
        env=_env(url, ws, BACKUP_PASSPHRASE_FILE=wrong.as_posix()),
        check=False,
    )
    assert bad_key.returncode == 7
    with engine.connect() as conn:  # nothing was restored by either attempt
        assert conn.execute(text("SELECT to_regclass('notes')")).scalar() is None
    _bash(
        "restore.sh",
        out.as_posix(),
        "--yes",
        env=_env(url, ws, BACKUP_PASSPHRASE_FILE=secret.as_posix()),
    )
    assert _rows(engine) == [(1, "alpha"), (2, "beta"), (3, "γ unicode")]


def test_an_empty_passphrase_file_is_refused_up_front(database, tmp_path):
    name, url, engine = database
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    r = _bash(
        "backup.sh",
        (tmp_path / "b").as_posix(),
        env=_env(url, _make_workspace(tmp_path), BACKUP_PASSPHRASE_FILE=empty.as_posix()),
        check=False,
    )
    assert r.returncode == 6 and not list((tmp_path / "b").glob("*.enc"))
