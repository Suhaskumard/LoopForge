"""Crash-recovery drill: kill a real worker process mid-run and prove another one finishes the task.

What it does (all local, no network, no Docker, no API key):
  1. builds a SQLite database with the real migrations and queues one task as a worker job;
  2. starts worker A (a real `python -m app.worker` subprocess, slow fake LLM) and waits until the
     Planner has finished and the Builder is in flight;
  3. kills worker A (SIGKILL-equivalent: `Popen.kill()`), leaving its lease and job behind;
  4. starts worker B, which must notice the expired lease, take the task over, and finish it
     from the checkpoint.
It then checks the evidence: the task is COMPLETED, the Planner ran exactly once (completed work was not
repeated), the dead worker's job was failed as "worker lost", a resume job finished, and worker B logged a
lease takeover. Exit status 0 = all checks passed.

Usage: python scripts/chaos_drill.py [--keep] [--timeout 90]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def worker_env(work: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "TEST_"))}
    env.update(
        DATABASE_URL=f"sqlite:///{work / 'chaos.db'}",
        WORKSPACE_ROOT=str(work / "workspaces"),
        ENVIRONMENT="development",
        LLM_PROVIDER="fake",
        SANDBOX_BACKEND="fake",
        FAKE_LLM_DELAY_SECONDS="1.5",  # Planner, Builder, Reviewer: long enough to interrupt
        DOCUMENTATION_AGENT_ENABLED="false",
        RUN_MODE="queue",
        LEASE_TTL_SECONDS="2",
        WORKER_POLL_SECONDS="0.2",
        WORKER_RECOVER_SECONDS="1",
        PYTHONPATH=str(BACKEND),
        PYTHONUNBUFFERED="1",
    )
    return env


def start_worker(env: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "app.worker"],
        cwd=BACKEND,
        env=env,
        stdout=log.open("wb"),
        stderr=subprocess.STDOUT,
    )


def wait_for(predicate, timeout: float, what: str, interval: float = 0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(f"timed out waiting for {what}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--keep", action="store_true", help="keep the temp directory for inspection"
    )
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="loopforge_chaos_"))
    env = worker_env(work)
    print(f"working directory: {work}")
    problems: list[str] = []
    procs: list[subprocess.Popen[bytes]] = []
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND, env=env, check=True, capture_output=True,
        )  # fmt: skip
        # This process talks to the same database as the workers.
        os.environ.update(env)
        sys.path.insert(0, str(BACKEND))
        from sqlalchemy import func, select

        from app.database.models import AgentRun, Iteration, Job, Project, Task, User
        from app.database.session import SessionLocal
        from app.schemas.project import ProjectCreate
        from app.services import (
            job_service,
            org_service,
            project_service,
            run_service,
            task_service,
        )
        from app.services.task_service import TaskStatus

        with SessionLocal() as db:
            user = User(email="chaos@example.com", password_hash="x")
            db.add(user)
            db.commit()
            org = org_service.create_personal_org(db, user)
            project = project_service.create_project(
                db, org.id, user.id, ProjectCreate(name="chaos")
            )
            task = task_service.create_task(
                db, project, "Build a small employee API with tests.", 5, []
            )
            task_id = task.id
            run_service.prepare_start(db, task)  # PENDING -> PLANNING, as the API does
            job_service.enqueue(db, task_id, "start")

        def agent_count(name: str, status: str) -> int:
            with SessionLocal() as db:
                return int(
                    db.scalar(
                        select(func.count())
                        .select_from(AgentRun)
                        .join(Iteration, AgentRun.iteration_id == Iteration.id)
                        .where(Iteration.task_id == task_id, AgentRun.agent_name == name,
                               AgentRun.status == status)
                    )
                    or 0
                )  # fmt: skip

        print("starting worker A ...")
        a = start_worker(env, work / "worker_a.log")
        procs.append(a)
        wait_for(lambda: agent_count("Planner", "success") >= 1, args.timeout, "Planner to finish")
        print("Planner finished; Builder is in flight: killing worker A now")
        a.kill()
        a.wait(timeout=10)
        killed_at = time.monotonic()
        with SessionLocal() as db:
            status_after_kill = db.get(Task, task_id).status
        print(f"worker A is dead (exit {a.returncode}); task is stranded in {status_after_kill}")
        if status_after_kill in ("COMPLETED", "FAILED", "ESCALATED"):
            problems.append("the drill killed the worker too late: the task had already finished")

        print("starting worker B ...")
        b = start_worker(env, work / "worker_b.log")
        procs.append(b)

        def final_status() -> str | None:
            with SessionLocal() as db:
                status = db.get(Task, task_id).status
                return (
                    status
                    if TaskStatus(status)
                    in task_service.TERMINAL_STATES | {TaskStatus.FAILED, TaskStatus.ESCALATED}
                    else None
                )

        status = wait_for(final_status, args.timeout, "the task to reach a final state")
        recovery = time.monotonic() - killed_at
        print(f"task finished: {status} ({recovery:.1f}s after the crash)")

        with SessionLocal() as db:
            jobs = [(j.kind, j.status, j.error) for j in db.scalars(
                select(Job).where(Job.task_id == task_id).order_by(Job.created_at))]  # fmt: skip
            iterations = db.scalar(select(func.count()).select_from(Iteration)
                                   .where(Iteration.task_id == task_id)) or 0  # fmt: skip
        planner = agent_count("Planner", "success")
        builder = agent_count("Builder", "success")
        reviewer = agent_count("Reviewer", "success")
        b_log = (work / "worker_b.log").read_text(encoding="utf-8", errors="replace")
        takeover = [json.loads(x) for x in b_log.splitlines() if "lease takeover" in x]

        print(f"jobs: {jobs}")
        print(
            f"agent successes: Planner={planner} Builder={builder} Reviewer={reviewer}; iterations={iterations}"
        )
        if status != "COMPLETED":
            problems.append(f"task ended {status}, expected COMPLETED")
        if planner != 1:
            problems.append(f"Planner succeeded {planner} times: completed work was repeated")
        if builder != 1 or reviewer != 1:
            problems.append(f"Builder/Reviewer successes were {builder}/{reviewer}, expected 1/1")
        if not any(k == "start" and s == "failed" and "worker lost" in e for k, s, e in jobs):
            problems.append("the dead worker's job was not failed as 'worker lost'")
        if not any(k == "resume" and s == "done" for k, s, _ in jobs):
            problems.append("no resume job finished")
        if not takeover:
            problems.append("worker B did not log a lease takeover")
        else:
            print(f"takeover logged: {takeover[0]['msg']}")
    except Exception as exc:  # noqa: BLE001 - a drill reports every failure mode the same way
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    if problems:
        print("\nCHAOS DRILL: FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        "\nCHAOS DRILL: PASS (a killed worker was replaced and the task completed from its checkpoint)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
