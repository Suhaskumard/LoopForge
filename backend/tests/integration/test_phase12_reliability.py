"""Phase 12 reliability: migration lock, deployment files, runtime-only image dependencies."""

import ast
import importlib.metadata as md
import re
import sys
from pathlib import Path

import yaml

from app.database.migration_lock import MIGRATION_LOCK_KEY, migration_lock

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


# ---- migration lock ----------------------------------------------------------------------------


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeConnection:
    def __init__(self, dialect: str) -> None:
        self.dialect = _Dialect(dialect)
        self.statements: list[tuple[str, dict]] = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))

    def commit(self) -> None:
        self.commits += 1


def test_postgres_migrations_take_and_release_the_advisory_lock():
    conn = FakeConnection("postgresql")
    with migration_lock(conn):
        conn.execute("-- the migration itself --")
    sql = [s for s, _ in conn.statements]
    assert sql == [
        "SELECT pg_advisory_lock(:k)",
        "-- the migration itself --",
        "SELECT pg_advisory_unlock(:k)",
    ]
    assert all(p == {"k": MIGRATION_LOCK_KEY} for s, p in conn.statements if "advisory" in s)
    assert conn.commits == 1


def test_the_lock_is_released_when_the_migration_fails():
    conn = FakeConnection("postgresql")
    try:
        with migration_lock(conn):
            raise RuntimeError("bad migration")
    except RuntimeError:
        pass
    assert "pg_advisory_unlock" in conn.statements[-1][0]


def test_sqlite_needs_no_lock():
    conn = FakeConnection("sqlite")
    with migration_lock(conn):
        pass
    assert conn.statements == [] and conn.commits == 0


def test_alembic_env_uses_the_lock_and_a_pinging_engine():
    env = (BACKEND / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "migration_lock(connection)" in env and "pool_pre_ping=True" in env


# ---- compose + Dockerfile ----------------------------------------------------------------------


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def test_migrations_run_once_in_their_own_service_and_the_app_waits_for_it():
    services = _compose()
    assert services["migrate"]["command"] == "alembic upgrade head"
    assert services["migrate"]["restart"] == "no"
    for name in ("backend", "worker"):
        cond = services[name]["depends_on"]["migrate"]["condition"]
        assert cond == "service_completed_successfully", name
        assert "alembic" not in str(services[name].get("command", "")), name  # no per-replica race


def test_long_running_services_restart_and_share_a_workspace_volume():
    services = _compose()
    for name in ("db", "backend", "worker", "frontend"):
        assert services[name]["restart"] == "unless-stopped", name
    for name in ("backend", "worker"):
        assert any("workspaces:" in v for v in services[name]["volumes"]), name
        assert services[name]["environment"]["WORKSPACE_ROOT"] == "/data/workspaces"
    assert "workspaces" in yaml.safe_load((ROOT / "docker-compose.yml").read_text())["volumes"]


def test_backend_is_health_checked_and_resource_limited():
    backend = _compose()["backend"]
    assert "health/ready" in " ".join(backend["healthcheck"]["test"])
    assert backend["deploy"]["resources"]["limits"]["memory"]
    worker = _compose()["worker"]
    assert (
        worker["environment"]["RUN_MODE"] == "queue"
        and worker["environment"]["WORKER_METRICS_PORT"]
    )
    assert worker["stop_grace_period"].endswith("s") and worker["deploy"]["resources"]["limits"]


def test_dockerfile_ships_runtime_dependencies_only_and_execs_the_server():
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements-runtime.txt" in dockerfile
    assert not re.search(r"requirements\.txt", dockerfile.replace("requirements-runtime.txt", ""))
    assert "exec uvicorn" in dockerfile  # PID 1 receives SIGTERM
    assert "RUN_MIGRATIONS" in dockerfile and "alembic upgrade head &&" not in dockerfile


# ---- requirements split ------------------------------------------------------------------------


def _pins(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-r"):
            continue
        name, _, version = line.partition("==")
        assert version, f"{line!r} is not pinned"
        out[re.sub(r"\[.*\]", "", name).lower()] = version
    return out


def test_runtime_requirements_exclude_dev_tools_and_dev_requirements_include_runtime():
    runtime = _pins(BACKEND / "requirements-runtime.txt")
    dev_text = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "-r requirements-runtime.txt" in dev_text
    dev_only = set(_pins(BACKEND / "requirements.txt"))
    for tool in ("pytest", "pytest-cov", "ruff", "mypy", "bandit", "hypothesis", "coverage"):
        assert tool in dev_only and tool not in runtime, tool
    for needed in ("fastapi", "sqlalchemy", "alembic", "cryptography", "psycopg"):
        assert needed in runtime, needed


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _closure(roots: set[str]) -> set[str]:
    seen: set[str] = set()
    todo = [_norm(r) for r in roots]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = md.requires(name) or []
        except md.PackageNotFoundError:
            continue
        for req in requires:
            if "extra ==" in req:  # optional extras are not installed unless asked for
                continue
            m = re.match(r"[A-Za-z0-9_.-]+", req)
            if m:
                todo.append(_norm(m.group(0)))
    return seen


def test_every_third_party_import_in_app_is_covered_by_the_runtime_requirements():
    covered = _closure(set(_pins(BACKEND / "requirements-runtime.txt")))
    # uvicorn[standard] installs extras on purpose
    covered |= {"uvloop", "httptools", "websockets", "pyyaml", "watchfiles", "python-dotenv"}
    owners = md.packages_distributions()
    uncovered: dict[str, set[str]] = {}
    for path in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                else []
            )  # fmt: skip
            for mod in mods:
                top = mod.split(".")[0]
                if top == "app" or top in sys.stdlib_module_names:
                    continue
                dists = {_norm(d) for d in owners.get(top, [])}
                if not dists & covered:
                    uncovered.setdefault(top, set()).add(str(path.relative_to(BACKEND)))
    assert not uncovered, f"imports not provided by requirements-runtime.txt: {uncovered}"
