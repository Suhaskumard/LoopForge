"""Disaster-recovery drill on real PostgreSQL (Phase 17): measure RTO and RPO instead of asserting them.

Scenario: the database host is lost. The drill

 1. starts a PostgreSQL 16 container, migrates it to head and seeds an organization;
 2. runs a writer that appends one audit row every few milliseconds (the "live traffic");
 3. takes a real backup with scripts/backup.sh while the writer keeps going;
 4. keeps writing for --tail-seconds more, then KILLS the container (`docker kill`: no clean shutdown);
 5. provisions a replacement container, restores with scripts/restore.sh, runs the migrations, and
    checks the restored service: row integrity, the append-only audit triggers, /health/ready.

It prints one JSON document with the **measured** numbers:
  rto_seconds  - from the kill until the restored service answered /health/ready,
  rpo_seconds  - the age (at the kill) of the newest write that survived; rows_lost counts the writes
                 that were acknowledged to the writer but are not in the restored database.

What these numbers are and are not: one single-node container on the machine that ran the drill, a
small database, a backup taken `--tail-seconds` before the failure. RTO scales with database size and
RPO with your backup schedule (nightly backups => RPO up to a day). Treat them as proof that the
procedure works and as a floor, not as a production guarantee. Needs a Docker daemon (it FAILS without
one) and Git Bash for the backup scripts.

Usage: python scripts/dr_drill.py [--tail-seconds 3] [--writes-per-second 50]
                                  [--max-rto 300] [--max-rpo 30] [--out results.json]
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PYTHON = sys.executable
PORT = 5439  # loopback only; away from 5432 (a developer's own) and 5433 (the test database)
USER, PASSWORD, DB = "loopforge", "loopforge", "loopforge_dr"
URL = f"postgresql+psycopg://{USER}:{PASSWORD}@127.0.0.1:{PORT}/{DB}"
IMAGE = "postgres:16"


def sh(*cmd: str, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kw)


def find_bash() -> str:
    if os.environ.get("BASH_EXE"):
        return os.environ["BASH_EXE"]
    git = shutil.which("git")
    if git:  # <git>/cmd/git.exe -> <git>/bin/bash.exe (Git Bash sees the same filesystem as Python)
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    raise SystemExit("FAIL: no suitable bash (install Git for Windows or set BASH_EXE)")


def start_db(name: str) -> None:
    sh("docker", "rm", "-f", name, check=False)
    sh(
        "docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{PORT}:5432",
        "-e", f"POSTGRES_USER={USER}", "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-e", f"POSTGRES_DB={DB}",
        IMAGE,
    )  # fmt: skip
    wait_ready(name)


def wait_ready(name: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = sh("docker", "exec", name, "pg_isready", "-U", USER, "-d", DB, check=False)
        if r.returncode == 0:
            # pg_isready is true during the init-script restart; require a real query to succeed twice
            q = sh("docker", "exec", name, "psql", "-U", USER, "-d", DB, "-tAc", "select 1", check=False)
            if q.stdout.strip() == "1":
                time.sleep(0.5)
                q = sh("docker", "exec", name, "psql", "-U", USER, "-d", DB, "-tAc", "select 1", check=False)
                if q.stdout.strip() == "1":
                    return
        time.sleep(0.4)
    raise SystemExit(f"FAIL: PostgreSQL in {name} did not become ready")


def migrate() -> None:
    env = {**os.environ, "DATABASE_URL": URL}
    sh(PYTHON, "-m", "alembic", "upgrade", "head", cwd=BACKEND, env=env)


class Writer(threading.Thread):
    """Appends audit rows; remembers what was acknowledged (commit returned) and when."""

    def __init__(self, rate: float) -> None:
        super().__init__(daemon=True)
        self.interval = 1.0 / rate
        self.stop = threading.Event()
        self.acked: list[tuple[int, float]] = []  # (seq, wall-clock at commit)
        self.error: str | None = None

    def run(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.database.models import AuditLog

        engine = create_engine(URL, pool_pre_ping=True)
        seq = 0
        while not self.stop.is_set():
            seq += 1
            try:
                with Session(engine) as db:
                    db.add(AuditLog(org_id=None, actor_id=None, action="dr.tick", target_type="drill",
                                    target_id=str(seq), detail={"seq": seq}, ip=""))  # fmt: skip
                    db.commit()
                self.acked.append((seq, time.time()))
            except Exception as exc:  # the container was killed under us: expected, stop cleanly
                self.error = type(exc).__name__
                return
            time.sleep(self.interval)


def restored_state(name: str) -> dict:
    def q(sql: str) -> str:
        return sh("docker", "exec", name, "psql", "-U", USER, "-d", DB, "-tAc", sql).stdout.strip()

    delete_blocked = sh(
        "docker", "exec", name, "psql", "-U", USER, "-d", DB, "-tAc",
        "delete from audit_log where action = 'dr.tick'", check=False,
    ).returncode != 0  # fmt: skip
    return {
        "max_seq": int(q("select coalesce(max((detail->>'seq')::int), 0) from audit_log where action='dr.tick'")),
        "rows": int(q("select count(*) from audit_log where action='dr.tick'")),
        "orgs": int(q("select count(*) from organizations")),
        "audit_delete_blocked": delete_blocked,
        "alembic_version": q("select version_num from alembic_version"),
    }  # fmt: skip


def health_ready() -> bool:
    code = (
        "from fastapi.testclient import TestClient; from app.main import app; "
        "r = TestClient(app).get('/health/ready'); import sys; sys.exit(0 if r.status_code == 200 else 1)"
    )
    env = {**os.environ, "DATABASE_URL": URL}
    return subprocess.run([PYTHON, "-c", code], cwd=BACKEND, env=env, capture_output=True).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail-seconds", type=float, default=3.0, help="writes between backup and failure")
    ap.add_argument("--head-seconds", type=float, default=2.0, help="writes before the backup starts")
    ap.add_argument("--writes-per-second", type=float, default=50.0)
    ap.add_argument("--max-rto", type=float, default=None, help="fail if RTO exceeds this (seconds)")
    ap.add_argument("--max-rpo", type=float, default=None, help="fail if RPO exceeds this (seconds)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if sh("docker", "info", check=False).returncode != 0:
        print("FAIL: no Docker daemon is reachable (start Docker Desktop)", file=sys.stderr)
        return 1
    bash = find_bash()
    os.environ["DATABASE_URL"] = URL  # set before the app is imported
    sys.path.insert(0, str(BACKEND))

    primary, replacement = f"lf-dr-primary-{uuid.uuid4().hex[:6]}", f"lf-dr-replacement-{uuid.uuid4().hex[:6]}"
    work = Path(tempfile.mkdtemp(prefix="lf-dr-"))
    (work / "workspaces").mkdir()
    (work / "workspaces" / "seed.txt").write_text("workspace file", encoding="utf-8")
    writer = Writer(args.writes_per_second)
    result: dict = {}
    try:
        print(f"[1/6] starting PostgreSQL ({primary}) and migrating ...", file=sys.stderr)
        start_db(primary)
        migrate()

        print("[2/6] live writes, then a backup while they continue ...", file=sys.stderr)
        writer.start()
        time.sleep(args.head_seconds)
        backup_dir = work / "backup"
        env = {**os.environ, "DATABASE_URL": URL, "PG_CONTAINER": primary,
               "WORKSPACE_ROOT": str(work / "workspaces")}  # fmt: skip
        t0 = time.time()
        b = subprocess.run([bash, (ROOT / "scripts" / "backup.sh").as_posix(), backup_dir.as_posix()],
                           capture_output=True, text=True, env=env, timeout=600)  # fmt: skip
        backup_seconds = time.time() - t0
        if b.returncode != 0:
            print(b.stdout, b.stderr, file=sys.stderr)
            raise SystemExit("FAIL: backup.sh failed")
        backup_done_at = time.time()
        backup_acked = len(writer.acked)

        print(f"[3/6] {args.tail_seconds}s more traffic, then the disaster (docker kill) ...", file=sys.stderr)
        time.sleep(args.tail_seconds)
        t_fail = time.time()
        sh("docker", "kill", primary)
        writer.stop.set()
        writer.join(timeout=10)
        acked_at_failure = [a for a in writer.acked if a[1] <= t_fail]
        last_seq, last_ts = acked_at_failure[-1]

        print("[4/6] provisioning a replacement and restoring ...", file=sys.stderr)
        sh("docker", "rm", "-f", primary, check=False)
        start_db(replacement)
        t_provisioned = time.time()
        renv = {**env, "PG_CONTAINER": replacement}
        r = subprocess.run([bash, (ROOT / "scripts" / "restore.sh").as_posix(), backup_dir.as_posix(), "--yes"],
                           capture_output=True, text=True, env=renv, timeout=900)  # fmt: skip
        if r.returncode != 0:
            print(r.stdout, r.stderr, file=sys.stderr)
            raise SystemExit("FAIL: restore.sh failed")
        t_restored = time.time()

        print("[5/6] migrating and verifying the restored service ...", file=sys.stderr)
        migrate()
        state = restored_state(replacement)
        ready = health_ready()
        t_ready = time.time()

        print("[6/6] computing RTO / RPO ...", file=sys.stderr)
        survived_ts = next((ts for seq, ts in reversed(acked_at_failure) if seq <= state["max_seq"]), None)
        checks = {
            "restored_rows_are_a_gap_free_prefix": state["rows"] == state["max_seq"],
            "nothing_invented": state["max_seq"] <= last_seq,
            "backup_contained_the_early_writes": state["max_seq"] >= 1,
            "audit_log_still_append_only": state["audit_delete_blocked"],
            "service_ready_after_restore": ready,
            "migrated_to_head": bool(state["alembic_version"]),
        }
        result = {
            "what": "single-node PostgreSQL 16 container on the machine that ran the drill (NOT a production topology)",
            "host": platform.platform(),
            "writes_per_second": args.writes_per_second,
            "backup_seconds": round(backup_seconds, 2),
            "rto_seconds": round(t_ready - t_fail, 2),
            "rto_breakdown_seconds": {
                "provision_database": round(t_provisioned - t_fail, 2),
                "restore": round(t_restored - t_provisioned, 2),
                "migrate_verify_ready": round(t_ready - t_restored, 2),
            },
            "rpo_seconds": round(t_fail - survived_ts, 2) if survived_ts else None,
            "rows_acknowledged": last_seq,
            "rows_restored": state["rows"],
            "rows_lost": last_seq - state["max_seq"],
            "rows_acknowledged_before_backup_finished": backup_acked,
            "seconds_between_backup_and_failure": round(t_fail - backup_done_at, 2),
            "checks": checks,
        }
    finally:
        writer.stop.set()
        for c in (primary, replacement):
            sh("docker", "rm", "-f", c, check=False)
        shutil.rmtree(work, ignore_errors=True)

    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    failed = [k for k, ok in result["checks"].items() if not ok]
    if failed:
        print(f"FAIL: checks failed: {failed}", file=sys.stderr)
        return 1
    if args.max_rto is not None and result["rto_seconds"] > args.max_rto:
        print(f"FAIL: RTO {result['rto_seconds']}s exceeds {args.max_rto}s", file=sys.stderr)
        return 1
    if args.max_rpo is not None and (result["rpo_seconds"] is None or result["rpo_seconds"] > args.max_rpo):
        print(f"FAIL: RPO {result['rpo_seconds']}s exceeds {args.max_rpo}s", file=sys.stderr)
        return 1
    print("DR DRILL: PASS", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
