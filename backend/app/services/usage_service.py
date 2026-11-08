"""Usage reports for an organization (Phase 18): who used how much, over a period.

Everything is derived from rows that already exist (``agent_runs`` joined to tasks and projects);
nothing is
measured separately. Cost is ``tokens / 1000 * price_per_1k(model)`` using the configured price map
(``MODEL_PRICES_JSON``, else the blended default): an **estimate for budgeting, not billing data**
- the
provider's invoice is the authority. Timestamps are UTC; the period is ``[start, end)``.
"""

import csv
import io
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import AgentRun, Iteration, Project, Task, User

GROUPS = ("project", "member", "agent", "model", "day")
MAX_DAYS = 366
COLUMNS = (
    "key", "label", "tasks", "agent_runs", "tokens", "estimated_cost_usd", "agent_seconds",
)  # fmt: skip


class ReportError(ValueError):
    pass


def period(
    start: date | None, end: date | None, today: date | None = None
) -> tuple[datetime, datetime]:
    """Inclusive start and end dates -> [start, end) datetimes. Default: this month so far."""
    now = today or datetime.utcnow().date()
    first = start or now.replace(day=1)
    last = end or now
    if last < first:
        raise ReportError("'to' must not be before 'from'")
    if (last - first).days >= MAX_DAYS:
        raise ReportError(f"a report covers at most {MAX_DAYS} days")
    return (
        datetime.combine(first, datetime.min.time()),
        datetime.combine(last + timedelta(days=1), datetime.min.time()),
    )


def report(
    db: Session, org_id: uuid.UUID, start: datetime, end: datetime, group_by: str
) -> dict[str, Any]:
    if group_by not in GROUPS:
        raise ReportError(f"group_by must be one of {', '.join(GROUPS)}")
    rows = db.execute(
        select(
            AgentRun.started_at,
            AgentRun.tokens_used,
            AgentRun.duration_seconds,
            AgentRun.agent_name,
            AgentRun.model,
            Task.id,
            Project.id,
            Project.name,
            User.email,
            Task.created_by,
        )  # fmt: skip
        .join(Iteration, AgentRun.iteration_id == Iteration.id)
        .join(Task, Iteration.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .outerjoin(User, User.id == Task.created_by)
        .where(Project.org_id == org_id, AgentRun.started_at >= start, AgentRun.started_at < end)
    )
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label": "",
            "tasks": set(),
            "agent_runs": 0,
            "tokens": 0,
            "cost": 0.0,
            "secs": 0.0,
        }
    )
    for started, tokens, secs, agent, model, task_id, project_id, project, email, creator in rows:
        key, label = {
            "project": (str(project_id), project),
            "member": (str(creator or "unknown"), email or "unknown"),
            "agent": (agent, agent),
            "model": (model or "unknown", model or "unknown"),
            "day": (started.date().isoformat(), started.date().isoformat()),
        }[group_by]
        g = groups[key]
        g["label"] = label
        g["tasks"].add(task_id)
        g["agent_runs"] += 1
        g["tokens"] += tokens or 0
        g["cost"] += (tokens or 0) / 1000 * settings.price_per_1k(model)
        g["secs"] += secs or 0.0
    out = [
        {
            "key": k,
            "label": g["label"],
            "tasks": len(g["tasks"]),
            "agent_runs": g["agent_runs"],
            "tokens": g["tokens"],
            "estimated_cost_usd": round(g["cost"], 6),
            "agent_seconds": round(g["secs"], 2),
        }  # fmt: skip
        for k, g in sorted(groups.items())
    ]
    all_tasks: set[Any] = set().union(*(g["tasks"] for g in groups.values())) if groups else set()
    return {
        "period": {
            "from": start.date().isoformat(),
            "to": (end - timedelta(days=1)).date().isoformat(),
        },
        "group_by": group_by,
        "rows": out,
        "totals": {
            "tasks": len(all_tasks),
            "agent_runs": sum(r["agent_runs"] for r in out),
            "tokens": sum(r["tokens"] for r in out),
            "estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in out), 6),
            "agent_seconds": round(sum(r["agent_seconds"] for r in out), 2),
        },
        "note": "Cost is an estimate from token counts and the price map, not billing data.",
    }  # fmt: skip


def _safe(cell: Any) -> Any:
    """Neutralise spreadsheet formula injection: a label like "=HYPERLINK(...)" stays text."""
    if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + cell
    return cell


def to_csv(data: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["period_from", "period_to", "group_by", *COLUMNS])
    for r in data["rows"]:
        w.writerow(
            [data["period"]["from"], data["period"]["to"], data["group_by"]]
            + [_safe(r[c]) for c in COLUMNS]
        )
    t = data["totals"]
    w.writerow(
        [data["period"]["from"], data["period"]["to"], data["group_by"], "TOTAL", "", t["tasks"],
         t["agent_runs"], t["tokens"], t["estimated_cost_usd"], t["agent_seconds"]]
    )  # fmt: skip
    return buf.getvalue()
