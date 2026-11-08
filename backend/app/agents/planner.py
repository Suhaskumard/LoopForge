"""Planner Agent: natural-language requirement -> validated plan + persisted requirements.

The Planner has no workspace access and may not write code (spec §4 "May not").
"""

import json
from collections.abc import Callable

from sqlalchemy import delete

from app.agents.base import AgentContext, OutputRejected, call_agent, wrap_untrusted
from app.agents.repo_map import build_repo_map
from app.database.models import Requirement
from app.execution.languages import LanguageProfile, get_profile
from app.schemas.plan import ProjectPlan
from app.services import workspace

NAME = "Planner"

SYSTEM = """You are the Planner agent of an autonomous software engineering platform.
Turn the user's requirement into a project plan for a {framework}.
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

SYSTEM_JS_NOTE = """
- This is a JavaScript/TypeScript project tested with Jest; set framework to "Node.js".
  Include package.json (dependencies pinned to exact versions) instead of requirements.txt;
  test files end in .test.js/.test.ts.
  Only jest, ts-jest, typescript, eslint, @types/jest and @types/node are available."""

SYSTEM_REPO_NOTE = """
- Set framework to "FastAPI" for Python and "Node.js" for JavaScript/TypeScript.
- An EXISTING repository is provided (map below, inside <untrusted_input>). Plan the SMALLEST set
  of changes: list ONLY the files you will modify or add, with action "modify" (file already in the
  repository) or "create". Set base to "existing". Never list untouched files. Keep the existing
  tests passing and add or extend tests for the change. Do not add requirements.txt/package.json
  unless a dependency really changes."""


def _validator(profile: LanguageProfile, seed: dict[str, str]) -> Callable[[ProjectPlan], None]:
    def validate(plan: ProjectPlan) -> None:
        paths = {f.path for f in plan.files}
        if not seed:
            if plan.base != "new":
                raise OutputRejected("base must be 'new' when there is no existing repository")
            if profile.manifest not in paths:
                raise OutputRejected(f"plan must include {profile.manifest}")
            return
        if plan.base != "existing":
            raise OutputRejected("base must be 'existing' for an existing repository")
        for f in plan.files:
            if f.action == "modify" and f.path not in seed:
                raise OutputRejected(f"cannot modify {f.path}: not in the repository")

    return validate


def run(ctx: AgentContext, requirement: str) -> ProjectPlan:
    profile = get_profile(ctx.task.project.language)
    seed = workspace.read_seed(ctx.task.id) if ctx.task.source_hash else {}
    system = SYSTEM.replace("{framework}", profile.framework_label)
    if profile.name == "javascript":
        system += SYSTEM_JS_NOTE
    user = f"Requirement:\n{wrap_untrusted(requirement)}"
    if seed:
        system += SYSTEM_REPO_NOTE
        repo_map = json.dumps(build_repo_map(seed, profile), indent=1)
        user += f"\nExisting repository map:\n{wrap_untrusted(repo_map)}"
    plan = call_agent(
        ctx,
        agent_name=NAME,
        system=system,
        user=user,
        response_model=ProjectPlan,
        input_summary=f"requirement: {requirement}",
        validate=_validator(profile, seed),
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
