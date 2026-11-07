"""Verifier Agent (3.5): deterministic, no LLM. The test report comes from real execution only.

It checks the dependency policy, runs pytest in the sandbox, stores stdout/stderr as log
artifacts and persists a `test_results` row. It never edits code and never invents results.
"""

from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.config import settings
from app.database.models import AgentRun, TestResult
from app.evaluation.test_runner import TestFailure, TestSummary, run_tests
from app.execution.dependencies import check_requirements
from app.execution.sandbox import Sandbox
from app.services import workspace

NAME = "Verifier"


def _record(db: Session, ctx: AgentContext, summary: TestSummary, extra: dict[str, object]) -> None:
    db.add(
        TestResult(
            iteration_id=ctx.iteration.id,
            total_tests=summary.total,
            passed=summary.passed,
            failed=summary.failed,
            skipped=summary.skipped,
            coverage=summary.coverage,
            details={**summary.as_dict(), **extra},
        )
    )
    db.commit()


def run(ctx: AgentContext, sandbox: Sandbox) -> TestSummary:
    """Execute the iteration's tests. Raises SandboxError on infrastructure failure."""
    db, task, it = ctx.db, ctx.task, ctx.iteration
    run_row = AgentRun(
        iteration_id=it.id, agent_name=NAME, input_summary="execute tests", status="running"
    )
    db.add(run_row)
    db.commit()
    src = workspace.iteration_dir(task.id, it.iteration_number)
    try:
        req = src / "requirements.txt"
        violations = check_requirements(req.read_text(encoding="utf-8")) if req.is_file() else []
        if violations:
            summary = TestSummary(
                failed=1,
                failures=[TestFailure("<dependencies>", "; ".join(violations), "")],
            )
            _record(db, ctx, summary, {"blocked": "dependency policy", "violations": violations})
            run_row.status, run_row.output_summary = "success", "blocked by dependency policy"
            db.commit()
            return summary

        out = workspace.out_dir(task.id, it.iteration_number)
        summary, result = run_tests(sandbox, src, out, settings.max_execution_seconds)
        for name, text in (
            ("pytest-stdout.txt", result.stdout),
            ("pytest-stderr.txt", result.stderr),
        ):
            workspace.write_log(
                db,
                task_id=task.id,
                iteration_id=it.id,
                iteration_number=it.iteration_number,
                name=name,
                content=text,
            )
        _record(db, ctx, summary, {})
        run_row.status = "success"
        run_row.output_summary = (
            f"{summary.passed} passed, {summary.failed} failed, {summary.skipped} skipped"
        )
        run_row.duration_seconds = summary.duration_seconds
        db.commit()
        return summary
    except BaseException as exc:
        run_row.status, run_row.error_message = "failed", f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        raise
