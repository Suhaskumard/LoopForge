"""Builder Agent: approved plan -> structured file changes written to the task workspace.

The Builder emits file changes only; it has no shell access (spec §4 "May not run shell freely").
Output must match the plan's file set exactly (complete project, nothing extra).
"""

from collections.abc import Callable

from sqlalchemy import select

from app.agents.base import AgentContext, OutputRejected, call_agent, wrap_untrusted
from app.database.models import Requirement
from app.schemas.plan import BuilderOutput, ProjectPlan
from app.services import workspace
from app.services.workspace import WrittenFile

NAME = "Builder"

SYSTEM = """You are the Builder agent of an autonomous software engineering platform.
Implement the approved plan as a complete, working Python FastAPI project.
Rules:
- Produce EXACTLY the files listed in the plan: no more, no fewer, same paths.
- Write real, runnable code and real unit tests (pytest). Pin nothing that is not in the plan's
  dependencies; requirements.txt must list the plan's dependencies.
- Paths are relative POSIX paths inside the project. No absolute paths, no '..', no hidden files.
- Output file contents only. Never include shell commands, install scripts, secrets or code that
  touches files outside the project."""


def _check_against_plan(plan: ProjectPlan) -> Callable[[BuilderOutput], None]:
    planned = {f.path for f in plan.files}

    def validate(out: BuilderOutput) -> None:
        produced = {f.path for f in out.files}
        missing, extra = sorted(planned - produced), sorted(produced - planned)
        if missing or extra:
            raise OutputRejected(
                f"file set differs from plan; missing={missing} unexpected={extra}"
            )

    return validate


def run(ctx: AgentContext, plan: ProjectPlan) -> list[WrittenFile]:
    output = call_agent(
        ctx,
        agent_name=NAME,
        system=SYSTEM,
        user=(
            "Approved plan (JSON):\n"
            f"{wrap_untrusted(plan.model_dump_json(indent=1))}\n"
            f"Original requirement:\n{wrap_untrusted(ctx.task.requirement)}"
        ),
        response_model=BuilderOutput,
        input_summary=f"plan for {plan.project_name}: {len(plan.files)} files",
        validate=_check_against_plan(plan),
    )
    written = workspace.write_changes(
        ctx.db,
        task_id=ctx.task.id,
        iteration_id=ctx.iteration.id,
        iteration_number=ctx.iteration.iteration_number,
        changes=output.files,
    )
    _map_requirements(ctx, plan)
    return written


def _map_requirements(ctx: AgentContext, plan: ProjectPlan) -> None:
    """Record which written files implement each requirement (Addendum 16.1 traceability)."""
    rows = ctx.db.scalars(select(Requirement).where(Requirement.task_id == ctx.task.id)).all()
    for row in rows:
        row.impl_mapping = [f.path for f in plan.files if row.req_id in f.implements]
    ctx.db.commit()
