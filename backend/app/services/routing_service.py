"""Round 12: smart model routing. Learn from the organization's own runs which model each agent
should use: the cheapest one whose tasks are accepted (almost) as often as the best one's."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import AgentRun, Iteration, Organization, Project, Task
from app.schemas.advanced import ROUTABLE_AGENTS, ModelStat, Recommendation

WINDOW_DAYS = 90
MIN_TASKS = 5  # evidence needed before a model is recommended
TOLERANCE = 0.10  # accept rate may be this far below the best and still win on cost
FINISHED = ("COMPLETED", "FAILED", "ESCALATED")


def stats(db: Session, org_id: uuid.UUID, now: datetime | None = None) -> list[ModelStat]:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    rows = db.execute(
        select(AgentRun.agent_name, AgentRun.model, AgentRun.tokens_used, Task.id, Task.status)
        .join(Iteration, AgentRun.iteration_id == Iteration.id)
        .join(Task, Iteration.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .where(
            Project.org_id == org_id,
            AgentRun.model.is_not(None),
            AgentRun.started_at >= now - timedelta(days=WINDOW_DAYS),
        )
    )
    agg: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"runs": 0, "tokens": 0, "tasks": {}}
    )
    for agent, model, tokens, task_id, status in rows:
        a = agg[(agent, model)]
        a["runs"] += 1
        a["tokens"] += tokens or 0
        a["tasks"][task_id] = status
    out = []
    for (agent, model), a in sorted(agg.items()):
        finished = [s for s in a["tasks"].values() if s in FINISHED]
        accepted = sum(s == "COMPLETED" for s in finished)
        per_run = a["tokens"] / a["runs"]
        out.append(
            ModelStat(
                agent=agent,
                model=model,
                runs=a["runs"],
                tasks=len(finished),
                accepted=accepted,
                accept_rate=round(accepted / len(finished), 3) if finished else None,
                tokens_per_run=round(per_run, 1),
                cost_per_run=round(per_run / 1000 * settings.price_per_1k(model), 6),
            )
        )
    return out


def recommend(all_stats: list[ModelStat]) -> list[Recommendation]:
    out = []
    for agent in ROUTABLE_AGENTS:
        cands = [s for s in all_stats if s.agent == agent and s.tasks >= MIN_TASKS and s.accept_rate is not None]
        if not cands:
            out.append(
                Recommendation(
                    agent=agent, model=None,
                    reason=f"Not enough evidence yet: needs {MIN_TASKS}+ finished tasks per model.",
                )  # fmt: skip
            )
            continue
        best = max(s.accept_rate or 0 for s in cands)
        good = [s for s in cands if (s.accept_rate or 0) >= best - TOLERANCE]
        pick = min(good, key=lambda s: (s.cost_per_run, -(s.accept_rate or 0)))
        reason = (
            f"Accepted {round((pick.accept_rate or 0) * 100)}% of {pick.tasks} tasks at "
            f"${pick.cost_per_run:.4f}/run"
        )
        if len(good) > 1:
            reason += f"; the cheapest within {round(TOLERANCE * 100)} points of the best ({round(best * 100)}%)."
        out.append(Recommendation(agent=agent, model=pick.model, reason=reason))
    return out


def routing_for(db: Session, org_id: uuid.UUID) -> dict[str, str]:
    org = db.get(Organization, org_id)
    return dict(org.model_routing or {}) if org is not None else {}


def set_routing(db: Session, org: Organization, routing: dict[str, str]) -> dict[str, str]:
    clean = {}
    for agent, model in routing.items():
        if agent not in ROUTABLE_AGENTS:
            raise ValueError(f"unknown agent {agent!r}; expected one of {', '.join(ROUTABLE_AGENTS)}")
        if model:
            clean[agent] = model
    org.model_routing = clean
    db.commit()
    return clean
