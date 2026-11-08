"""Builder Agent: approved plan -> structured file changes written to the task workspace.

The Builder emits file changes only; it has no shell access (spec §4 "May not run shell freely").
Greenfield: output must match the plan's file set exactly (complete project, nothing extra).
Existing repository (Phase 8): output covers exactly the planned files - the ones being modified or
added - and is applied on top of the seed, so every untouched file is carried over unchanged.
"""

from collections.abc import Callable

from sqlalchemy import select

from app.agents.base import AgentContext, OutputRejected, call_agent, wrap_untrusted
from app.database.models import Requirement
from app.execution.languages import LanguageProfile, get_profile
from app.schemas.plan import BuilderOutput, FilesOutput, PatchOutput, ProjectPlan
from app.services import workspace
from app.services.workspace import WrittenFile

NAME = "Builder"
MAX_CONTEXT_CHARS = 80_000

SYSTEM = """You are the Builder agent of an autonomous software engineering platform.
Implement the approved plan as a complete, working {framework}.
Rules:
- Produce EXACTLY the files listed in the plan: no more, no fewer, same paths.
- Write real, runnable code and real unit tests ({test_cmd}). Pin nothing that is not in the plan's
  dependencies; {manifest} must list the plan's dependencies.
- Paths are relative POSIX paths inside the project. No absolute paths, no '..', no hidden files.
- Output file contents only. Never include shell commands, install scripts, secrets or code that
  touches files outside the project."""

SYSTEM_PATCH = """You are the Builder agent of an autonomous software engineering platform.
You are changing an EXISTING {framework}. Apply the approved plan.
Rules:
- Output EXACTLY the files listed in the plan (those you modify or add), each with its COMPLETE new
  content. Do not output untouched files.
- For "modify" files the current content is shown (inside <untrusted_input>): keep everything that
  is not part of the change - style, imports, unrelated code - exactly as it is.
- Keep every existing test; add or extend tests ({test_cmd}) for the change. Never delete or weaken
  an existing test to make it pass.
- Paths are relative POSIX paths. No absolute paths, no '..', no hidden files.
- Output file contents only. Never include shell commands, install scripts, secrets or code that
  touches files outside the project."""


def _check_against_plan(
    plan: ProjectPlan, profile: LanguageProfile, *, patch: bool
) -> Callable[[FilesOutput], None]:
    planned = {f.path for f in plan.files}

    def validate(out: FilesOutput) -> None:
        produced = {f.path for f in out.files}
        missing, extra = sorted(planned - produced), sorted(produced - planned)
        if missing or extra:
            raise OutputRejected(
                f"file set differs from plan; missing={missing} unexpected={extra}"
            )
        if not patch and profile.manifest not in produced:
            raise OutputRejected(f"builder output must include {profile.manifest}")

    return validate


def _current_files(plan: ProjectPlan, seed: dict[str, str]) -> str:
    parts: list[str] = []
    budget = MAX_CONTEXT_CHARS
    for f in plan.files:
        if f.action == "modify" and f.path in seed:
            text = seed[f.path][: max(budget, 0)]
            budget -= len(text)
            parts.append(f"--- {f.path} (current) ---\n{text}")
    return "\n".join(parts)


def run(ctx: AgentContext, plan: ProjectPlan) -> list[WrittenFile]:
    profile = get_profile(ctx.task.project.language)
    seed = workspace.read_seed(ctx.task.id) if ctx.task.source_hash else {}
    patch = bool(seed)
    fmt = {
        "framework": profile.framework_label,
        "test_cmd": profile.test_command_label,
        "manifest": profile.manifest,
    }
    system = SYSTEM_PATCH if patch else SYSTEM
    for key, value in fmt.items():
        system = system.replace("{" + key + "}", value)
    user = (
        "Approved plan (JSON):\n"
        f"{wrap_untrusted(plan.model_dump_json(indent=1))}\n"
        f"Original requirement:\n{wrap_untrusted(ctx.task.requirement)}"
    )
    if patch:
        current = wrap_untrusted(_current_files(plan, seed))
        user += f"\nCurrent content of the files to modify:\n{current}"
    output = call_agent(
        ctx,
        agent_name=NAME,
        system=system,
        user=user,
        response_model=PatchOutput if patch else BuilderOutput,
        input_summary=f"plan for {plan.project_name}: {len(plan.files)} files",
        validate=_check_against_plan(plan, profile, patch=patch),
    )
    if patch:
        written = workspace.fork_iteration(
            ctx.db,
            task_id=ctx.task.id,
            from_number=0,  # the seed; untouched files carry over, changed ones are replaced
            to_iteration_id=ctx.iteration.id,
            to_number=ctx.iteration.iteration_number,
            changes=output.files,
        )
    else:
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
