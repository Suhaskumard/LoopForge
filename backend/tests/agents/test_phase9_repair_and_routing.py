"""Phase 9: Repair uses failure classes, targeted context, the test guard and past repairs;
per-agent model routing reaches the LLM client and the agent_runs row."""

import pytest
from sqlalchemy import select

from app.agents import repair
from app.agents.base import AgentContext, AgentFailure
from app.config import settings
from app.database.models import AgentRun, Iteration, Project, RepairHistory, Task, User
from app.demo.employee_management import builder_output, repair_output
from app.schemas.loop import RepairOutput
from app.schemas.plan import FileChange
from app.services import org_service, workspace
from app.utils.token_tracker import TokenTracker

REPORT = {
    "execution": [
        {
            "channel": "execution",
            "nodeid": "tests/test_routes.py::test_update",
            "error_type": "AssertionError",
            "message": "assert 404 == 200",
            "traceback": "app/routes.py:43: assert 404 == 200",
        }
    ]
}


@pytest.fixture
def written(ctx, db):
    workspace.write_changes(
        db,
        task_id=ctx.task.id,
        iteration_id=ctx.iteration.id,
        iteration_number=1,
        changes=builder_output().files,
    )


def test_prompt_carries_the_failure_class_strategy_and_targeted_context(ctx, llm, written):
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1")
    prompt = llm.calls[0].user
    assert "Failure class: logic." in prompt
    assert "--- app/routes.py\n" in prompt  # named in the failure: full text
    assert "--- tests/__init__.py (outline only" in prompt  # unrelated: outline only
    assert "pytest.ini (outline only: 42 chars; symbols: (not a source file))" in prompt


def test_switches_off_restore_the_old_prompt(ctx, llm, written):
    llm.queue(repair_output())
    repair.run(
        ctx,
        REPORT,
        "fp1",
        failure_routing=False,
        targeted_context=False,
        test_guard=False,
        history_retrieval=False,
    )
    prompt = llm.calls[0].user
    assert "Failure class" not in prompt and "outline only" not in prompt
    assert "--- app/main.py\n" in prompt


def test_failure_class_and_fingerprint_are_recorded(ctx, db, llm, written):
    llm.queue(repair_output())
    new = repair.run(ctx, REPORT, "fp-abc")
    rec = db.scalars(select(RepairHistory)).one()
    assert rec.failure_class == "logic" and rec.fingerprint == "fp-abc"
    assert new.feedback["repair"]["failure_class"] == "logic"


def _weakened_tests() -> RepairOutput:
    original = next(f.content for f in builder_output().files if f.path == "tests/test_routes.py")
    stripped = "\n".join(line for line in original.splitlines() if "assert" not in line) + "\n"
    return RepairOutput(
        root_cause="the tests are too strict",
        explanation="loosen them",
        changes=[FileChange(path="tests/test_routes.py", content=stripped, action="modify")],
    )


def test_a_repair_that_weakens_tests_is_rejected_then_retried(ctx, db, llm, written):
    llm.queue(_weakened_tests(), repair_output())  # rejected, then a proper fix on the retry
    new = repair.run(ctx, REPORT, "fp1")
    assert new.feedback["repair"]["files_modified"] == ["app/routes.py"]
    assert "REJECTED: tests may not be weakened" in llm.calls[1].user


def test_weakening_twice_fails_the_agent_and_writes_nothing(ctx, db, llm, written):
    llm.queue(_weakened_tests(), _weakened_tests())
    with pytest.raises(AgentFailure):
        repair.run(ctx, REPORT, "fp1")
    assert len(db.scalars(select(Iteration)).all()) == 1


def test_guard_can_be_ablated(ctx, db, llm, written):
    llm.queue(_weakened_tests())
    new = repair.run(ctx, REPORT, "fp1", test_guard=False)
    assert new.feedback["repair"]["files_modified"] == ["tests/test_routes.py"]


# ---- retrieval of similar past repairs -----------------------------------------------------


def _other_task_with_history(
    db, org_id, creator_id, *, outcome="resolved", fingerprint="fp1", cls="logic"
):
    project = Project(user_id=creator_id, org_id=org_id, name="old")
    db.add(project)
    db.flush()
    task = Task(project_id=project.id, requirement="older task that was repaired earlier")
    db.add(task)
    db.flush()
    db.add(
        RepairHistory(
            task_id=task.id,
            root_cause="OLD-CAUSE off-by-one id",
            proposed_fix="OLD-FIX use the requested id",
            outcome=outcome,
            fingerprint=fingerprint,
            failure_class=cls,
        )
    )
    db.commit()


def test_similar_resolved_repairs_from_the_same_owner_are_offered(ctx, db, llm, written):
    _other_task_with_history(db, ctx.task.project.org_id, ctx.task.project.user_id)
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1")
    prompt = llm.calls[0].user
    assert "fixed similar failures before" in prompt and "OLD-FIX use the requested id" in prompt


def test_same_class_is_used_when_the_fingerprint_differs(ctx, db, llm, written):
    _other_task_with_history(
        db, ctx.task.project.org_id, ctx.task.project.user_id, fingerprint="other"
    )
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp-new")
    assert "OLD-FIX" in llm.calls[0].user


@pytest.mark.parametrize(
    "kwargs",
    [{"outcome": "unresolved"}, {"cls": "syntax", "fingerprint": "zzz"}],
    ids=["unresolved-repairs-are-not-hints", "different-class-and-fingerprint"],
)
def test_irrelevant_history_is_not_offered(ctx, db, llm, written, kwargs):
    _other_task_with_history(db, ctx.task.project.org_id, ctx.task.project.user_id, **kwargs)
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1")
    assert "OLD-FIX" not in llm.calls[0].user


def test_other_organizations_history_is_never_offered(ctx, db, llm, written):
    stranger = User(email="s@x.com", password_hash="x")
    db.add(stranger)
    db.flush()
    stranger_org = org_service.create_personal_org(db, stranger)
    _other_task_with_history(db, stranger_org.id, stranger.id)
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1")
    assert "OLD-FIX" not in llm.calls[0].user


@pytest.mark.parametrize("kwargs", [{"history_retrieval": False}, {"memory": False}])
def test_retrieval_respects_its_switches(ctx, db, llm, written, kwargs):
    _other_task_with_history(db, ctx.task.project.org_id, ctx.task.project.user_id)
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1", **kwargs)
    assert "OLD-FIX" not in llm.calls[0].user


# ---- per-agent model routing ---------------------------------------------------------------


def test_default_routing_uses_the_client_default(ctx, db, llm, written):
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1")
    assert llm.calls[0].model is None


def test_configured_model_reaches_the_client_and_the_agent_run(ctx, db, llm, written, monkeypatch):
    monkeypatch.setattr(settings, "model_repair", "strong-model")
    llm.queue(repair_output())
    repair.run(ctx, REPORT, "fp1")
    assert llm.calls[0].model == "strong-model"
    run = db.scalars(select(AgentRun).where(AgentRun.agent_name == "Repair")).one()
    assert run.model == "strong-model"


def test_model_for_maps_agent_names_and_ignores_unknown_ones(monkeypatch):
    monkeypatch.setattr(settings, "model_planner", "cheap")
    monkeypatch.setattr(settings, "model_documentation", "")
    assert settings.model_for("Planner") == "cheap"
    assert settings.model_for("Documentation") is None
    assert settings.model_for("Verifier") is None  # no such override: default model


def test_context_object_is_unchanged():
    # AgentContext keeps its shape: routing is looked up per call, not stored.
    assert set(AgentContext.__dataclass_fields__) == {"db", "task", "iteration", "llm", "tracker"}
    assert TokenTracker
