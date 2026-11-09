"""The organization's workspace as a graph: projects, tasks, failure classes and files (Round 8).

Everything is scoped to one organization. `learned_from` mirrors the repair agent's memory lookup
(`agents.repair._similar_fixes`): only RESOLVED repairs from tasks that allow being learned from.
"""

import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Iteration, Project, RepairHistory, Task
from app.schemas.graph import GraphEdge, GraphNode, GraphOut, RepairOut

MAX_TASKS = 300
MAX_FILES = 40


def failure_key(h: RepairHistory) -> str:
    return h.failure_class or h.failure_category or "unclassified"


def build_graph(db: Session, org_id: uuid.UUID, max_tasks: int = MAX_TASKS) -> GraphOut:
    tasks = list(
        db.scalars(
            select(Task)
            .join(Project, Task.project_id == Project.id)
            .where(Project.org_id == org_id)
            .order_by(Task.created_at.desc(), Task.id)
            .limit(max_tasks + 1)
        )
    )
    truncated = len(tasks) > max_tasks
    tasks = tasks[:max_tasks]
    task_ids = [t.id for t in tasks]
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    project_ids = {t.project_id for t in tasks}
    projects = (
        list(db.scalars(select(Project).where(Project.id.in_(project_ids)))) if project_ids else []
    )
    task_count = Counter(t.project_id for t in tasks)
    for p in projects:
        nodes.append(
            GraphNode(
                id=f"p:{p.id}",
                type="project",
                label=p.name,
                meta={"project_id": str(p.id), "language": p.language, "tasks": task_count[p.id]},
            )
        )

    # latest quality score per task
    quality: dict[uuid.UUID, float | None] = {}
    if task_ids:
        latest = (
            select(Iteration.task_id, func.max(Iteration.iteration_number).label("n"))
            .where(Iteration.task_id.in_(task_ids))
            .group_by(Iteration.task_id)
            .subquery()
        )
        rows = db.execute(
            select(Iteration.task_id, Iteration.quality_score).join(
                latest,
                (Iteration.task_id == latest.c.task_id)
                & (Iteration.iteration_number == latest.c.n),
            )
        )
        quality = {tid: q for tid, q in rows}

    for t in tasks:
        nodes.append(
            GraphNode(
                id=f"t:{t.id}",
                type="task",
                label=t.requirement[:80],
                status=t.status,
                meta={
                    "task_id": str(t.id),
                    "iterations": t.current_iteration,
                    "max_iterations": t.max_iterations,
                    "quality": quality.get(t.id),
                    "created_at": t.created_at.isoformat(),
                    "learnable": t.learn_from_task,
                },
            )
        )
        edges.append(GraphEdge(source=f"p:{t.project_id}", target=f"t:{t.id}", kind="contains"))

    # Round 9: task chains (continued from another task's code) and re-runs / A/B variants
    shown = {t.id for t in tasks}
    for t in tasks:
        if t.source_type == "task" and t.source_ref:
            try:
                parent = uuid.UUID(t.source_ref)
            except ValueError:
                parent = None
            if parent in shown:
                edges.append(
                    GraphEdge(source=f"t:{t.id}", target=f"t:{parent}", kind="chained_from")
                )
        if t.rerun_of in shown:
            edges.append(GraphEdge(source=f"t:{t.id}", target=f"t:{t.rerun_of}", kind="rerun_of"))

    repairs = (
        list(
            db.scalars(
                select(RepairHistory)
                .where(RepairHistory.task_id.in_(task_ids))
                .order_by(RepairHistory.created_at)
            )
        )
        if task_ids
        else []
    )

    failures: Counter[str] = Counter()
    resolved: Counter[str] = Counter()
    failed_pairs: set[tuple[uuid.UUID, str]] = set()
    files: Counter[str] = Counter()
    touched: dict[str, set[uuid.UUID]] = {}
    for h in repairs:
        key = failure_key(h)
        failures[key] += 1
        resolved[key] += h.outcome == "resolved"
        failed_pairs.add((h.task_id, key))
        for f in h.files_modified or []:
            if isinstance(f, str) and f:
                files[f] += 1
                touched.setdefault(f, set()).add(h.task_id)

    for key, n in failures.items():
        nodes.append(
            GraphNode(
                id=f"f:{key}",
                type="failure",
                label=key,
                meta={"count": n, "resolved": resolved[key]},
            )
        )
    for tid, key in sorted(failed_pairs, key=lambda x: (str(x[0]), x[1])):
        edges.append(GraphEdge(source=f"t:{tid}", target=f"f:{key}", kind="failed_with"))

    for path, n in files.most_common(MAX_FILES):
        nodes.append(GraphNode(id=f"file:{path}", type="file", label=path, meta={"repairs": n}))
        for tid in sorted(touched[path], key=str):
            edges.append(GraphEdge(source=f"t:{tid}", target=f"file:{path}", kind="touched"))

    # learned_from: a later repair whose fingerprint matches an earlier resolved, learnable one
    learnable = {t.id for t in tasks if t.learn_from_task}
    first_fix: dict[str, RepairHistory] = {}
    links: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for h in repairs:  # chronological
        if not h.fingerprint:
            continue
        source = first_fix.get(h.fingerprint)
        if source is not None and source.task_id != h.task_id:
            links.add((h.task_id, source.task_id))
        if h.fingerprint not in first_fix and h.outcome == "resolved" and h.task_id in learnable:
            first_fix[h.fingerprint] = h
    for a, b in sorted(links, key=lambda x: (str(x[0]), str(x[1]))):
        edges.append(GraphEdge(source=f"t:{a}", target=f"t:{b}", kind="learned_from"))

    return GraphOut(nodes=nodes, edges=edges, truncated=truncated)


def list_repairs(
    db: Session,
    org_id: uuid.UUID,
    failure_class: str | None = None,
    outcome: str | None = None,
    limit: int = 200,
) -> list[RepairOut]:
    stmt = (
        select(RepairHistory, Task)
        .join(Task, RepairHistory.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .where(Project.org_id == org_id)
        .order_by(RepairHistory.created_at.desc())
        .limit(limit)
    )
    if outcome:
        stmt = stmt.where(RepairHistory.outcome == outcome)
    rows = db.execute(stmt).all()
    out = []
    for h, t in rows:
        if failure_class and failure_key(h) != failure_class:
            continue
        out.append(
            RepairOut(
                id=h.id,
                task_id=t.id,
                task_requirement=t.requirement[:200],
                task_status=t.status,
                learnable=t.learn_from_task,
                failure_class=failure_key(h),
                failure_category=h.failure_category,
                fingerprint=h.fingerprint,
                root_cause=h.root_cause,
                proposed_fix=h.proposed_fix,
                files_modified=list(h.files_modified or []),
                outcome=h.outcome,
                regression_status=h.regression_status,
                tokens_used=h.tokens_used,
                duration_seconds=h.duration_seconds,
                created_at=h.created_at,
            )
        )
    return out
