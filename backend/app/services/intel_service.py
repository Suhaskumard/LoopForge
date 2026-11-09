"""Round 9 "loop intelligence": forecasts, task chains, re-runs, regression watches, A/B variants.

Re-runs and A/B variants are NEW tasks (a COMPLETED task never changes state again); they point at
the task they repeat via `rerun_of`, and copy its seed so the comparison is fair.
"""

import logging
import threading
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database.models import (
    AgentRun,
    Iteration,
    Project,
    RegressionWatch,
    Task,
)
from app.services import (
    analytics_service,
    notification_service,
    repo_import,
    source_service,
    task_service,
    workspace,
)
from app.services.repo_import import RepoImportError

log = logging.getLogger("loopforge.intel")

FINISHED = ("COMPLETED", "FAILED", "ESCALATED")
AB_AGENTS = ("Planner", "Builder", "Repair", "Reviewer", "Documentation")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class IntelError(Exception):
    """A request that cannot be honoured (maps to 409/422)."""


# ---- forecast -----------------------------------------------------------------------------------


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(p * (len(s) - 1))))]


def forecast(db: Session, org_id: uuid.UUID, language: str, words: int) -> dict[str, Any]:
    """What finished tasks like this one cost and how they ended (p50 / p90)."""
    rows = list(
        db.execute(
            select(Task, Project.language)
            .join(Project, Task.project_id == Project.id)
            .where(Project.org_id == org_id, Task.status.in_(FINISHED))
            .order_by(Task.created_at.desc())
            .limit(300)
        ).all()
    )
    same_lang = [t for t, lang in rows if lang == language]
    similar = [t for t in same_lang if words and 0.5 <= len(t.requirement.split()) / words <= 2]
    if len(similar) >= 3:
        sample, scope = similar, "similar"
    elif len(same_lang) >= 3:
        sample, scope = same_lang, "language"
    else:
        sample, scope = [t for t, _ in rows], "organization"
    if not sample:
        return {"basis": 0, "scope": "none", "accept_rate": None, "tokens": None, "cost": None,
                "iterations": None, "seconds": None}  # fmt: skip

    ids = [t.id for t in sample]
    runs_by_task: dict[uuid.UUID, list[AgentRun]] = defaultdict(list)
    for run, task_id in db.execute(
        select(AgentRun, Iteration.task_id)
        .join(Iteration, AgentRun.iteration_id == Iteration.id)
        .where(Iteration.task_id.in_(ids))
    ):
        runs_by_task[task_id].append(run)
    spans: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    for task_id, started, completed in db.execute(
        select(Iteration.task_id, Iteration.started_at, Iteration.completed_at).where(
            Iteration.task_id.in_(ids)
        )
    ):
        spans[task_id] += [d for d in (started, completed) if d is not None]

    tokens = [float(sum(r.tokens_used for r in runs_by_task[t.id])) for t in sample]
    cost = [analytics_service.cost_of_runs(runs_by_task[t.id]) for t in sample]
    iters = [float(t.current_iteration) for t in sample]
    secs = [(max(spans[t.id]) - min(spans[t.id])).total_seconds() for t in sample if spans[t.id]]

    def band(values: list[float], digits: int = 0) -> dict[str, float] | None:
        lo, hi = _pct(values, 0.5), _pct(values, 0.9)
        if lo is None or hi is None:
            return None
        return {"p50": round(lo, digits), "p90": round(hi, digits)}

    return {
        "basis": len(sample),
        "scope": scope,
        "accept_rate": round(sum(t.status == "COMPLETED" for t in sample) / len(sample), 3),
        "tokens": band(tokens),
        "cost": band(cost, 4),
        "iterations": band(iters, 1),
        "seconds": band(secs),
    }


# ---- chains and clones --------------------------------------------------------------------------


def accepted_files(task: Task, db: Session) -> dict[str, str]:
    """The source of the task's latest ACCEPTED iteration (what a follow-up task builds on)."""
    it = db.scalars(
        select(Iteration)
        .where(Iteration.task_id == task.id, Iteration.status == "accepted")
        .order_by(Iteration.iteration_number.desc())
    ).first()
    if it is None:
        raise IntelError("that task has no accepted version to continue from")
    base = workspace.iteration_dir(task.id, it.iteration_number)
    return {rel: workspace.read_file(base, rel) for rel in workspace.list_source_files(base)}


def seed_from_task(db: Session, task: Task, source: Task) -> None:
    """Task chains: the new task starts from `source`'s accepted code, as an existing repo."""
    if source.status != "COMPLETED":
        raise IntelError(f"only a COMPLETED task can be continued (that one is {source.status})")
    files = accepted_files(source, db)
    try:
        result = repo_import.import_files(files)  # same rules as an upload: paths, sizes, secrets
        source_service.seed_task(db, task, result, str(source.id))
    except RepoImportError as exc:
        raise IntelError(str(exc)) from None


def clone_for_rerun(
    db: Session,
    src: Task,
    *,
    actor: uuid.UUID | None,
    model_overrides: dict[str, str] | None = None,
    experiment: str | None = None,
) -> Task:
    """A fresh PENDING copy of `src` (same requirement, criteria, budgets and starting code)."""
    project = db.get(Project, src.project_id)
    if project is None:  # the task row references it, so this only happens on corrupt data
        raise IntelError("the task's project no longer exists")
    clone = task_service.create_task(
        db,
        project,
        src.requirement,
        src.max_iterations,
        list(src.acceptance_criteria),
        token_budget=src.token_budget,
        max_cost=src.max_cost,
        require_plan_approval=False,  # unattended re-runs must not wait for a person
        source_type=src.source_type if src.source_type != "git" else "none",
        source_ref=src.source_ref if src.source_type != "git" else None,
        created_by=actor,
        learn_from_task=src.learn_from_task,
    )
    clone.rerun_of = src.id
    clone.experiment = experiment
    clone.model_overrides = dict(model_overrides or {})
    if src.source_hash:
        seed = workspace.read_seed(src.id)
        if seed:
            workspace.write_seed(clone.id, seed)
            clone.source_hash = src.source_hash
    elif src.source_type == "git":  # re-importing could pick up a moved branch: freeze the original
        clone.source_type = "none"
    db.commit()
    db.refresh(clone)
    return clone


# ---- starting runs outside a request -------------------------------------------------------------


class Starter(Protocol):
    def __call__(self, task_id: uuid.UUID) -> None: ...


class ThreadBackground:
    """`dispatch` needs something with add_task(); outside a request, run each job in a thread."""

    def add_task(self, fn: Any, *args: Any) -> None:
        threading.Thread(target=fn, args=args, daemon=True, name="loopforge-rerun").start()


def start(db: Session, task: Task, starter: Starter) -> None:
    from app.services import run_service

    run_service.prepare_start(db, task)
    starter(task.id)


# ---- regression watch ---------------------------------------------------------------------------


def set_watch(
    db: Session, task: Task, org_id: uuid.UUID, interval_hours: int, active: bool, actor: uuid.UUID
) -> RegressionWatch:
    if task.status != "COMPLETED":
        raise IntelError("only an accepted (COMPLETED) task can be watched for regressions")
    watch = db.scalars(select(RegressionWatch).where(RegressionWatch.task_id == task.id)).first()
    if watch is None:
        watch = RegressionWatch(
            task_id=task.id, org_id=org_id, created_by=actor, last_result="",
            next_run_at=_now() + timedelta(hours=interval_hours),
        )  # fmt: skip
        db.add(watch)
    elif watch.interval_hours != interval_hours or (active and not watch.active):
        watch.next_run_at = _now() + timedelta(hours=interval_hours)
    watch.interval_hours = interval_hours
    watch.active = active
    db.commit()
    db.refresh(watch)
    return watch


def rerun(db: Session, task: Task, actor: uuid.UUID | None, starter: Starter) -> Task:
    if task.status != "COMPLETED":
        raise IntelError("only an accepted (COMPLETED) task can be re-run as a regression check")
    clone = clone_for_rerun(db, task, actor=actor)
    watch = db.scalars(select(RegressionWatch).where(RegressionWatch.task_id == task.id)).first()
    if watch is not None:
        watch.last_run_task_id = clone.id
        watch.last_result = "running"
        db.commit()
    start(db, clone, starter)
    return clone


def run_due(db: Session, starter: Starter, now: datetime | None = None) -> int:
    """Re-run every active watch whose time has come. Returns how many runs were started."""
    now = now or _now()
    due = list(
        db.scalars(
            select(RegressionWatch).where(
                RegressionWatch.active.is_(True), RegressionWatch.next_run_at <= now
            )
        )
    )
    started = 0
    for watch in due:
        watch.next_run_at = now + timedelta(hours=watch.interval_hours)
        db.commit()  # move the schedule first: a crash below must not re-run in a tight loop
        task = db.get(Task, watch.task_id)
        if task is None or task.status != "COMPLETED":
            continue
        try:
            rerun(db, task, watch.created_by, starter)
            started += 1
        except Exception:
            log.exception("regression re-run of task %s failed to start", watch.task_id)
            db.rollback()
    return started


def on_terminal(db: Session, task: Task) -> None:
    """A re-run finished: record the result on the watch and alert people if it regressed."""
    if task.rerun_of is None or task.experiment is not None:
        return
    watch = db.scalars(
        select(RegressionWatch).where(RegressionWatch.task_id == task.rerun_of)
    ).first()
    if watch is None or watch.last_run_task_id != task.id:
        return
    regressed = task.status != "COMPLETED"
    watch.last_result = "regressed" if regressed else "passing"
    db.commit()
    if regressed:
        notification_service.notify_safely(
            db, watch.org_id, "regression",
            f"Regression: a re-run no longer passes — {task.requirement[:70]}",
            {"task_id": str(task.id), "original_task_id": str(task.rerun_of),
             "status": task.status},
            roles=["developer", "approver", "admin"], dedupe_key=f"regression:{task.id}",
        )  # fmt: skip


class RegressionScheduler:
    """Inline mode has no worker process: a small daemon thread checks the watches."""

    def __init__(self, factory: sessionmaker[Session], starter_factory: Any) -> None:
        self.factory, self.starter_factory = factory, starter_factory
        self.stop = threading.Event()

    def loop(self) -> None:
        while not self.stop.wait(settings.regression_poll_seconds):
            try:
                with self.factory() as db:
                    run_due(db, self.starter_factory())
            except Exception:
                log.exception("regression scheduler pass failed")


# ---- A/B experiments ----------------------------------------------------------------------------


def start_experiment(
    db: Session,
    task: Task,
    agent: str,
    model_a: str,
    model_b: str,
    actor: uuid.UUID,
    starter: Starter,
) -> tuple[str, list[Task]]:
    if agent not in AB_AGENTS:
        raise IntelError(f"agent must be one of {', '.join(AB_AGENTS)}")
    if model_a == model_b:
        raise IntelError("pick two different models")
    experiment = uuid.uuid4().hex[:12]
    variants = [
        clone_for_rerun(db, task, actor=actor, model_overrides={agent: m}, experiment=experiment)
        for m in (model_a, model_b)
    ]
    for v in variants:
        start(db, v, starter)
    return experiment, variants


def experiment_rows(db: Session, org_id: uuid.UUID, experiment: str) -> list[dict[str, Any]]:
    tasks = list(
        db.scalars(
            select(Task)
            .join(Project, Task.project_id == Project.id)
            .where(Project.org_id == org_id, Task.experiment == experiment)
            .order_by(Task.created_at, Task.id)
        )
    )
    out = []
    for t in tasks:
        runs = list(
            db.scalars(
                select(AgentRun)
                .join(Iteration, AgentRun.iteration_id == Iteration.id)
                .where(Iteration.task_id == t.id)
            )
        )
        its = list(db.scalars(select(Iteration).where(Iteration.task_id == t.id)))
        stamps = [d for i in its for d in (i.started_at, i.completed_at) if d is not None]
        quality = max((i.quality_score for i in its if i.quality_score is not None), default=None)
        out.append(
            {
                "task_id": t.id,
                "status": t.status,
                "model_overrides": t.model_overrides or {},
                "iterations": t.current_iteration,
                "tokens": sum(r.tokens_used for r in runs),
                "cost": round(analytics_service.cost_of_runs(runs), 6),
                "quality": quality,
                "seconds": (max(stamps) - min(stamps)).total_seconds() if stamps else None,
                "rerun_of": t.rerun_of,
            }
        )
    return out
