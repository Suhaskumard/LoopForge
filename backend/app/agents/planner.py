"""Planner Agent: natural-language requirement -> validated plan + persisted requirements.

The Planner has no workspace access and may not write code (spec §4 "May not").
"""

from sqlalchemy import delete

from app.agents.base import AgentContext, call_agent, wrap_untrusted
from app.database.models import Requirement
from app.schemas.plan import ProjectPlan

NAME = "Planner"

SYSTEM = """You are the Planner agent of an autonomous software engineering platform.
Turn the user's requirement into a project plan for a Python FastAPI application.
Rules:
- Split the requirement into individual, testable requirements with ids REQ-001, REQ-002, ...
  Classify each as functional, non_functional, security or performance, and give a priority
  (critical, high, medium, low).
- Write measurable acceptance criteria.
- List every file to create (relative POSIX paths such as app/main.py; no absolute paths, no '..',
  no hidden files). Include tests and requirements.txt. For each file list the requirement ids it
  implements in `implements`.
- List pinned dependencies as name==version.
- Do NOT write any code."""


def run(ctx: AgentContext, requirement: str) -> ProjectPlan:
    plan = call_agent(
        ctx,
        agent_name=NAME,
        system=SYSTEM,
        user=f"Requirement:\n{wrap_untrusted(requirement)}",
        response_model=ProjectPlan,
        input_summary=f"requirement: {requirement}",
    )
    _persist(ctx, plan)
    return plan


def _persist(ctx: AgentContext, plan: ProjectPlan) -> None:
    db, task = ctx.db, ctx.task
    db.execute(delete(Requirement).where(Requirement.task_id == task.id))
    for item in plan.requirements:
        db.add(
            Requirement(
                task_id=task.id,
                req_id=item.req_id,
                description=item.description,
                req_type=item.type,
                priority=item.priority,
                impl_mapping=[],
                test_mapping=[],
                verification_status="pending",
            )
        )
    # Keep any criteria the user supplied, then add the planner's (de-duplicated, order-stable).
    merged = list(dict.fromkeys([*task.acceptance_criteria, *plan.acceptance_criteria]))
    task.acceptance_criteria = merged
    ctx.iteration.feedback = {**ctx.iteration.feedback, "plan": plan.model_dump()}
    db.commit()
