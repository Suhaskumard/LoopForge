"""KPI calculations (spec §9.1, §12.4; Addendum 22.11).

One module owns every formula so the dashboard, the API and the exit-gate check agree.
Definitions that matter:

* success rate    = COMPLETED / (COMPLETED + FAILED + ESCALATED); CANCELLED and unfinished tasks
                    are excluded from both sides;
* test pass rate  = passed / executed, using only the **latest** test_results row of every
                    iteration, so repeated runs of the same iteration are never double-counted;
* avg quality     = mean quality score of the final iteration of COMPLETED tasks;
* avg execution   = total execution time of COMPLETED tasks / COMPLETED tasks, where a task's
                    time runs from its first iteration start to its terminal status change;
* cost            = tokens x COST_PER_1K_TOKENS - an *estimate*, there is no billing data.
"""

import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    AgentRun,
    AuditEvent,
    Iteration,
    Project,
    RepairHistory,
    Task,
    TestResult,
)
from app.schemas.analytics import (
    AgentRunStat,
    AgentStatOut,
    AgentStatusOut,
    IterationAnalyticsOut,
    IterationStat,
    OverviewOut,
    TaskAnalyticsOut,
    TaskBrief,
)

ELIGIBLE = ("COMPLETED", "FAILED", "ESCALATED")
TERMINAL = ("COMPLETED", "FAILED", "ESCALATED", "CANCELLED")
AGENT_NAMES = ("Planner", "Builder", "Verifier", "Reviewer", "Repair", "Documentation")


def _ratio(num: float, den: float) -> float | None:
    return None if den == 0 else num / den


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def cost_of(tokens: int) -> float:
    return tokens / 1000 * settings.cost_per_1k_tokens


def latest_results(db: Session, iteration_ids: list[uuid.UUID]) -> dict[uuid.UUID, TestResult]:
    """The most recent test_results row per iteration (the only one that counts)."""
    if not iteration_ids:
        return {}
    rows = db.scalars(
        select(TestResult)
        .where(TestResult.iteration_id.in_(iteration_ids))
        .order_by(TestResult.created_at, TestResult.id)
    )
    return {r.iteration_id: r for r in rows}  # later rows overwrite earlier ones


def _terminal_times(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    if not task_ids:
        return {}
    out: dict[uuid.UUID, datetime] = {}
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.task_id.in_(task_ids), AuditEvent.event_type == "status_changed")
        .order_by(AuditEvent.created_at)
    )
    for e in rows:
        if e.event_data.get("to") in TERMINAL:
            out[e.task_id] = e.created_at
    return out


def _tokens_by_iteration(db: Session, iteration_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    totals: dict[uuid.UUID, int] = defaultdict(int)
    if iteration_ids:
        for run in db.scalars(select(AgentRun).where(AgentRun.iteration_id.in_(iteration_ids))):
            totals[run.iteration_id] += run.tokens_used
    return totals


def _task_seconds(its: list[Iteration], ended: datetime | None) -> float | None:
    if not its or ended is None:
        return None
    start = min(i.started_at for i in its)
    return max((ended - start).total_seconds(), 0.0)


def overview(db: Session, user_id: uuid.UUID) -> OverviewOut:
    tasks = list(
        db.scalars(
            select(Task)
            .join(Project, Task.project_id == Project.id)
            .where(Project.user_id == user_id)
            .order_by(Task.created_at.desc(), Task.id)
        )
    )
    task_ids = [t.id for t in tasks]
    its = (
        list(db.scalars(select(Iteration).where(Iteration.task_id.in_(task_ids))))
        if task_ids
        else []
    )
    by_task: dict[uuid.UUID, list[Iteration]] = defaultdict(list)
    for it in its:
        by_task[it.task_id].append(it)
    results = latest_results(db, [i.id for i in its])
    tokens = _tokens_by_iteration(db, [i.id for i in its])
    ended = _terminal_times(db, task_ids)

    by_status = Counter(t.status for t in tasks)
    completed = [t for t in tasks if t.status == "COMPLETED"]
    eligible = sum(by_status[s] for s in ELIGIBLE)

    executed = sum(r.total_tests for r in results.values())
    passed = sum(r.passed for r in results.values())

    qualities: list[float] = []
    for t in completed:
        final = max(by_task[t.id], key=lambda i: i.iteration_number, default=None)
        if final is not None and final.quality_score is not None:
            qualities.append(final.quality_score)

    seconds = [_task_seconds(by_task[t.id], ended.get(t.id)) for t in completed]
    measured = [s for s in seconds if s is not None]

    total_tokens = sum(tokens.values())
    started = sum(1 for t in tasks if by_task[t.id])
    iterations_of_completed = sum(len(by_task[t.id]) for t in completed)

    repairs = (
        list(db.scalars(select(RepairHistory).where(RepairHistory.task_id.in_(task_ids))))
        if task_ids
        else []
    )
    failure_distribution = Counter(r.failure_category or "unclassified" for r in repairs)
    outcomes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in repairs:
        outcomes[r.failure_category or "unclassified"][r.outcome or "pending"] += 1

    return OverviewOut(
        tasks_total=len(tasks),
        tasks_by_status=dict(by_status),
        eligible_finished=eligible,
        completed=len(completed),
        task_success_rate=_round(_ratio(len(completed) * 100, eligible), 2),
        average_iterations=_round(_ratio(iterations_of_completed, len(completed)), 3),
        test_pass_rate=_round(_ratio(passed * 100, executed), 2),
        tests_executed=executed,
        tests_passed=passed,
        average_quality_score=_round(_ratio(sum(qualities), len(qualities)), 2),
        average_execution_seconds=_round(_ratio(sum(measured), len(measured)), 3),
        average_cost=_round(_ratio(cost_of(total_tokens), started), 6),
        total_tokens=total_tokens,
        total_cost=round(cost_of(total_tokens), 6),
        iteration_efficiency=_round(
            _ratio(len(completed), sum(len(v) for v in by_task.values())), 4
        ),
        failure_distribution=dict(failure_distribution),
        repair_outcomes={k: dict(v) for k, v in outcomes.items()},
        recent_tasks=[
            TaskBrief(
                id=t.id,
                requirement=t.requirement[:140],
                status=t.status,
                iterations=len(by_task[t.id]),
                created_at=t.created_at.isoformat(),
            )
            for t in tasks[:8]
        ],
    )


def task_analytics(db: Session, task: Task) -> TaskAnalyticsOut:
    its = sorted(
        db.scalars(select(Iteration).where(Iteration.task_id == task.id)),
        key=lambda i: i.iteration_number,
    )
    ids = [i.id for i in its]
    results = latest_results(db, ids)
    runs: dict[uuid.UUID, list[AgentRun]] = defaultdict(list)
    if ids:
        for run in db.scalars(select(AgentRun).where(AgentRun.iteration_id.in_(ids))):
            runs[run.iteration_id].append(run)
    stats: list[IterationStat] = []
    for it in its:
        r = results.get(it.id)
        stats.append(
            IterationStat(
                number=it.iteration_number,
                status=it.status,
                quality_score=it.quality_score,
                tests_total=r.total_tests if r else 0,
                tests_passed=r.passed if r else 0,
                tests_failed=r.failed if r else 0,
                coverage=r.coverage if r else None,
                tokens=sum(x.tokens_used for x in runs[it.id]),
                duration_seconds=round(sum(x.duration_seconds for x in runs[it.id]), 3),
            )
        )
    total = sum(s.tokens for s in stats)
    categories = Counter(
        r.failure_category or "unclassified"
        for r in db.scalars(select(RepairHistory).where(RepairHistory.task_id == task.id))
    )
    return TaskAnalyticsOut(
        task_id=task.id,
        status=task.status,
        iterations=stats,
        total_tokens=total,
        estimated_cost=round(cost_of(total), 6),
        execution_seconds=_round(
            _task_seconds(its, _terminal_times(db, [task.id]).get(task.id)), 3
        ),
        quality_trend=[s.quality_score for s in stats],
        failure_categories=dict(categories),
    )


def iteration_analytics(db: Session, it: Iteration) -> IterationAnalyticsOut:
    per_agent: dict[str, list[AgentRun]] = defaultdict(list)
    for run in db.scalars(select(AgentRun).where(AgentRun.iteration_id == it.id)):
        per_agent[run.agent_name].append(run)
    agents = [
        AgentRunStat(
            agent=name,
            runs=len(rs),
            tokens=sum(r.tokens_used for r in rs),
            duration_seconds=round(sum(r.duration_seconds for r in rs), 3),
        )
        for name, rs in sorted(per_agent.items())
    ]
    row = latest_results(db, [it.id]).get(it.id)
    tests: dict[str, Any] = (
        {
            "total": row.total_tests,
            "passed": row.passed,
            "failed": row.failed,
            "skipped": row.skipped,
            "coverage": row.coverage,
        }
        if row
        else {}
    )
    return IterationAnalyticsOut(
        iteration_id=it.id,
        number=it.iteration_number,
        status=it.status,
        quality_score=it.quality_score,
        tests=tests,
        agents=agents,
        total_tokens=sum(a.tokens for a in agents),
        duration_seconds=round(sum(a.duration_seconds for a in agents), 3),
        decision=it.feedback.get("decision"),
    )


def _agent_rows(db: Session, user_id: uuid.UUID) -> list[AgentRun]:
    return list(
        db.scalars(
            select(AgentRun)
            .join(Iteration, AgentRun.iteration_id == Iteration.id)
            .join(Task, Iteration.task_id == Task.id)
            .join(Project, Task.project_id == Project.id)
            .where(Project.user_id == user_id)
            .order_by(AgentRun.started_at, AgentRun.id)
        )
    )


def _agent_stat(name: str, rows: list[AgentRun]) -> AgentStatOut:
    finished = [r for r in rows if r.status != "running"]
    ok = sum(1 for r in finished if r.status == "success")
    return AgentStatOut(
        agent=name,
        runs=len(rows),
        successes=ok,
        failures=len(finished) - ok,
        success_rate=_round(_ratio(ok * 100, len(finished)), 2),
        average_duration_seconds=_round(
            _ratio(sum(r.duration_seconds for r in finished), len(finished)), 3
        ),
        tokens=sum(r.tokens_used for r in rows),
    )


def agent_analytics(db: Session, user_id: uuid.UUID) -> list[AgentStatOut]:
    grouped: dict[str, list[AgentRun]] = defaultdict(list)
    for r in _agent_rows(db, user_id):
        grouped[r.agent_name].append(r)
    return [_agent_stat(n, grouped.get(n, [])) for n in AGENT_NAMES]


def agent_status(db: Session, user_id: uuid.UUID, name: str) -> AgentStatusOut:
    rows = [r for r in _agent_rows(db, user_id) if r.agent_name == name]
    base = _agent_stat(name, rows)
    last = rows[-1] if rows else None
    return AgentStatusOut(
        **base.model_dump(),
        last_status=last.status if last else None,
        last_run_at=last.started_at.isoformat() if last else None,
    )
