"""Verifier Agent (3.5): deterministic, no LLM. The test report comes from real execution only.

It checks the dependency policy, runs pytest in the sandbox, stores stdout/stderr as log
artifacts and persists a `test_results` row. It never edits code and never invents results.
"""

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.config import settings
from app.database.models import AgentRun, Iteration, TestResult
from app.evaluation.affected_tests import affected_tests
from app.evaluation.changed_coverage import changed_line_coverage, changed_lines, read_line_coverage
from app.evaluation.mutation import run_mutation_check
from app.evaluation.test_runner import TestFailure, TestSummary, run_tests
from app.execution.languages import PYTHON, LanguageProfile, get_profile
from app.execution.sandbox import ExecResult, Sandbox
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


def _affected_paths(it: Iteration, src: Path, profile: LanguageProfile) -> list[str]:
    """Test files tied to what the last repair changed (none on the first iteration)."""
    changed = list((it.feedback.get("repair") or {}).get("files_modified", []))
    if not changed:
        return []
    files = {
        rel: (src / rel).read_text(encoding="utf-8") for rel in workspace.list_source_files(src)
    }
    return affected_tests(changed, files, profile)


def _verification_extras(
    it: Iteration,
    task_id: Any,
    src: Path,
    out: Path,
    sandbox: Sandbox,
    summary: TestSummary,
    profile: LanguageProfile,
    *,
    line_coverage: bool,
    mutation: bool,
) -> dict[str, object]:
    """Phase 16 report-only checks on the code a repair changed (Python only)."""
    if profile is not PYTHON or summary.partial:
        return {}
    new = {rel: (src / rel).read_text(encoding="utf-8") for rel in workspace.list_source_files(src)}
    prev_dir = workspace.iteration_dir(task_id, it.iteration_number - 1)
    old = (
        {
            rel: (prev_dir / rel).read_text(encoding="utf-8")
            for rel in workspace.list_source_files(prev_dir)
        }
        if it.iteration_number > 1 and prev_dir.is_dir()
        else {}
    )
    changed = {
        p: lines for p, lines in changed_lines(old, new).items() if not profile.is_test_file(p)
    }
    extra: dict[str, object] = {}
    if line_coverage and changed:
        cov = read_line_coverage(out / profile.coverage_name)
        if cov is not None:
            extra["changed_line_coverage"] = changed_line_coverage(changed, cov)
    if mutation and changed and summary.ok:  # a mutation check only means something on green tests
        scratch_out = out / "mutation"
        scratch_out.mkdir(parents=True, exist_ok=True)
        extra["mutation"] = run_mutation_check(
            sandbox, src, scratch_out, sorted(changed), settings.max_execution_seconds
        )
    return extra


def run(
    ctx: AgentContext,
    sandbox: Sandbox,
    affected_first: bool = False,
    changed_line_cov: bool = False,
    mutation_check: bool = False,
) -> TestSummary:
    """Execute the iteration's tests. Raises SandboxError on infrastructure failure."""
    db, task, it = ctx.db, ctx.task, ctx.iteration
    run_row = AgentRun(
        iteration_id=it.id, agent_name=NAME, input_summary="execute tests", status="running"
    )
    db.add(run_row)
    db.commit()
    src = workspace.iteration_dir(task.id, it.iteration_number)
    try:
        profile = get_profile(task.project.language)
        manifest = src / profile.manifest
        violations = (
            profile.check_dependencies(manifest.read_text(encoding="utf-8"))
            if manifest.is_file()
            else []
        )
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
        extra: dict[str, object] = {}
        chosen: tuple[TestSummary, ExecResult] | None = None
        only = _affected_paths(it, src, profile) if affected_first else []
        if only:  # Phase 16: run the tests tied to the change first; a failure is a cheap signal
            subset, sub_result = run_tests(
                sandbox, src, out, settings.max_execution_seconds, profile, only=only
            )
            extra = {"affected_first": only}
            if not subset.ok:
                chosen = (subset, sub_result)
                extra["scope"] = "affected tests only (full suite not run)"
        if chosen is None:  # the full suite ALWAYS runs before a verdict
            chosen = run_tests(sandbox, src, out, settings.max_execution_seconds, profile)
        summary, result = chosen
        if changed_line_cov or mutation_check:
            extra.update(
                _verification_extras(
                    it, task.id, src, out, sandbox, summary, profile,
                    line_coverage=changed_line_cov, mutation=mutation_check,
                )
            )  # fmt: skip
        label = profile.test_command_label
        for name, text in (
            (f"{label}-stdout.txt", result.stdout),
            (f"{label}-stderr.txt", result.stderr),
        ):
            workspace.write_log(
                db,
                task_id=task.id,
                iteration_id=it.id,
                iteration_number=it.iteration_number,
                name=name,
                content=text,
            )
        _record(db, ctx, summary, extra)
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
