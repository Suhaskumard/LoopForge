"""Documentation Agent (spec 4 table): final documentation only, after a terminal state.

It may not run before the task is finished and it can never change a verdict: the deterministic
report (services/report_service.py) is complete without it. This agent only writes a README for
the generated project, stored beside the logs - never over generated source files.
"""

import logging

from sqlalchemy import select

from app.agents.base import AgentContext, AgentFailure, call_agent, wrap_untrusted
from app.database.models import Iteration
from app.schemas.report import ReadmeOutput
from app.services import workspace
from app.services.report_service import README_NAME, TERMINAL

NAME = "Documentation"
log = logging.getLogger("loopforge.documenter")

SYSTEM = """You are the Documentation agent of an autonomous software engineering platform.
Write a concise README.md for the generated Python FastAPI project described below: what it does,
how to install and run it, how to run the tests, and the main endpoints.
Rules: describe only what the files and plan actually contain; do not claim features, test
results or security properties that are not evidenced; no secrets; no shell one-liners that
download or execute remote code. Respond with JSON {"content": "<markdown>"}."""


def run(ctx: AgentContext, plan_json: str) -> str | None:
    """Generate the README. Never fails the task: documentation must not affect the outcome."""
    if ctx.task.status not in TERMINAL:
        raise RuntimeError("Documentation agent may only run after a terminal state")
    last = ctx.db.scalars(
        select(Iteration)
        .where(Iteration.task_id == ctx.task.id)
        .order_by(Iteration.iteration_number.desc())
    ).first()
    if last is None or ctx.tracker.exceeded:
        return None
    ctx.iteration = last
    base = workspace.iteration_dir(ctx.task.id, last.iteration_number)
    names = workspace.list_source_files(base) if base.is_dir() else []
    try:
        out = call_agent(
            ctx,
            agent_name=NAME,
            system=SYSTEM,
            user=(
                f"Plan:\n{wrap_untrusted(plan_json[:20_000])}\n"
                f"Files:\n{wrap_untrusted(chr(10).join(names))}"
            ),
            response_model=ReadmeOutput,
            input_summary=f"README for {len(names)} files",
        )
    except AgentFailure as exc:
        log.warning("documentation skipped: %s", exc)
        return None
    workspace.write_log(
        ctx.db,
        task_id=ctx.task.id,
        iteration_id=last.id,
        iteration_number=last.iteration_number,
        name=README_NAME,
        content=out.content,
        artifact_type="doc",
    )
    return out.content
