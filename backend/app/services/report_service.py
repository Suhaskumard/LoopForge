"""Final engineering report (spec 15.1 "the system produces a final report with execution
evidence"). Built only from stored records; the Documentation Agent may add a README but can never
change a number or a verdict here."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    ApprovalRequest,
    Artifact,
    AuditEvent,
    Iteration,
    Requirement,
    Task,
)
from app.schemas.report import FinalReport, ReportIteration, ReportRequirement
from app.services import analytics_service, workspace

TERMINAL = ("COMPLETED", "FAILED", "ESCALATED", "CANCELLED")
README_NAME = "README.generated.md"

_OUTCOME = {
    "COMPLETED": "Accepted: every test passed and the independent review found no blocking issue.",
    "ESCALATED": "Escalated: the work was NOT accepted; a person must decide what happens next.",
    "FAILED": "Failed: the run stopped on an error; nothing here is accepted.",
    "CANCELLED": "Cancelled by the user before a verdict was reached.",
}


def _escalation_reason(db: Session, task: Task) -> str | None:
    if task.status not in ("ESCALATED", "FAILED"):
        return None
    ev = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.task_id == task.id, AuditEvent.event_type == "run_failed")
        .order_by(AuditEvent.created_at.desc())
    ).first()
    if ev is not None:
        return str(ev.event_data.get("reason", ""))[:500] or None
    last = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.task_id == task.id, AuditEvent.event_type == "decision")
        .order_by(AuditEvent.created_at.desc())
    ).first()
    return f"Decision Engine: {last.event_data.get('action')}" if last else None


def _source_files(db: Session, it: Iteration) -> list[dict[str, str]]:
    rows = db.scalars(
        select(Artifact).where(Artifact.iteration_id == it.id, Artifact.artifact_type == "source")
    )
    return [
        {"path": a.file_name, "sha256": a.file_hash}
        for a in sorted(rows, key=lambda a: a.file_name)
    ]


def build_report(db: Session, task: Task) -> FinalReport:
    its = sorted(
        db.scalars(select(Iteration).where(Iteration.task_id == task.id)),
        key=lambda i: i.iteration_number,
    )
    results = analytics_service.latest_results(db, [i.id for i in its])
    rows: list[ReportIteration] = []
    for it in its:
        r = results.get(it.id)
        fb = it.feedback
        rows.append(
            ReportIteration(
                number=it.iteration_number,
                status=it.status,
                tests_total=r.total_tests if r else 0,
                tests_passed=r.passed if r else 0,
                tests_failed=r.failed if r else 0,
                coverage=r.coverage if r else None,
                quality_score=it.quality_score,
                decision=(fb.get("decision") or {}).get("action"),
                repair_root_cause=(fb.get("repair") or {}).get("root_cause"),
                repair_files=list((fb.get("repair") or {}).get("files_modified", [])),
            )
        )
    last = its[-1] if its else None
    last_fb = last.feedback if last else {}
    review = last_fb.get("review") or {}
    quality = last_fb.get("quality") or {}
    final_tests = results.get(last.id) if last else None

    reqs = list(
        db.scalars(
            select(Requirement).where(Requirement.task_id == task.id).order_by(Requirement.req_id)
        )
    )
    plan = (its[0].feedback.get("plan") or {}) if its else {}
    impl: dict[str, list[str]] = {}
    for f in plan.get("files", []):
        for rid in f.get("implements", []):
            impl.setdefault(rid, []).append(f["path"])

    tokens = sum(analytics_service._tokens_by_iteration(db, [i.id for i in its]).values())
    approvals = [
        {"kind": a.kind, "status": a.status, "summary": a.summary, "iteration": a.iteration_number}
        for a in db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.task_id == task.id)
            .order_by(ApprovalRequest.created_at)
        )
    ]
    readme_path = workspace.log_dir(task.id, last.iteration_number) / README_NAME if last else None
    return FinalReport(
        task_id=task.id,
        requirement=task.requirement,
        status=task.status,
        outcome=_OUTCOME.get(task.status, "Still in progress: no verdict yet."),
        escalation_reason=_escalation_reason(db, task),
        iterations=rows,
        requirements=[
            ReportRequirement(
                req_id=r.req_id,
                description=r.description,
                req_type=r.req_type,
                priority=r.priority,
                implemented_in=impl.get(r.req_id, list(r.impl_mapping)),
                tested_in=list(r.test_mapping),
                verification_status=r.verification_status,
                evidence=r.evidence_ref,
            )
            for r in reqs
        ],
        acceptance_criteria=list(review.get("acceptance_criteria", [])),
        tests={
            "total": final_tests.total_tests if final_tests else 0,
            "passed": final_tests.passed if final_tests else 0,
            "failed": final_tests.failed if final_tests else 0,
            "coverage": final_tests.coverage if final_tests else None,
        },
        quality={
            "score": last.quality_score if last else None,
            "lint_findings": len(quality.get("ruff", [])),
            "high_security_findings": len(quality.get("bandit_high", [])),
            "critical_issues": review.get("critical_issues", 0),
        },
        files=_source_files(db, last) if last else [],
        total_tokens=tokens,
        estimated_cost=round(analytics_service.cost_of(tokens), 6),
        approvals=approvals,
        readme_generated=bool(readme_path and readme_path.exists()),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def render_markdown(r: FinalReport, readme: str | None = None) -> str:
    out = [
        f"# LoopForge engineering report - task {r.task_id}",
        "",
        f"**Status:** {r.status}  ",
        f"**Outcome:** {r.outcome}",
    ]
    if r.escalation_reason:
        out.append(f"  \n**Reason:** {r.escalation_reason}")
    out += ["", "## Requirement", "", f"> {r.requirement}", "", "## Evidence summary", ""]
    cov = "n/a" if r.tests["coverage"] is None else f"{r.tests['coverage']:.0f}%"
    out += [
        f"- Tests (final iteration): {r.tests['passed']}/{r.tests['total']} passed, coverage {cov}",
        f"- Lint findings: {r.quality['lint_findings']}; high-severity security findings: "
        f"{r.quality['high_security_findings']}; critical review issues: "
        f"{r.quality['critical_issues']}",
        f"- Tokens: {r.total_tokens:,}; estimated cost: ${r.estimated_cost:.4f} (estimate)",
        "",
        "## Iteration history",
        "",
        "| # | Status | Tests | Quality | Decision | Repair |",
        "|---|---|---|---|---|---|",
    ]
    for i in r.iterations:
        score = "-" if i.quality_score is None else f"{i.quality_score:.2f}"
        fix = (i.repair_root_cause or "-").replace("|", "/")[:80]
        out.append(
            f"| {i.number} | {i.status} | {i.tests_passed}/{i.tests_total} | {score} | "
            f"{i.decision or '-'} | {fix} |"
        )
    out += ["", "## Requirement traceability", ""]
    if r.requirements:
        out += [
            "| ID | Requirement | Implemented in | Tested in | Status |",
            "|---|---|---|---|---|",
        ]
        for q in r.requirements:
            out.append(
                f"| {q.req_id} | {q.description.replace('|', '/')[:80]} | "
                f"{', '.join(q.implemented_in) or '-'} | {', '.join(q.tested_in) or '-'} | "
                f"{q.verification_status} |"
            )
    else:
        out.append("No requirements recorded.")
    out += ["", "## Acceptance criteria", ""]
    out += [
        f"- [{'x' if c.get('met') else ' '}] {c.get('criterion')}" for c in r.acceptance_criteria
    ]
    if not r.acceptance_criteria:
        out.append("No review was recorded.")
    if r.approvals:
        out += ["", "## Human approvals", ""]
        out += [f"- {a['kind']} (iteration {a['iteration']}): {a['status']}" for a in r.approvals]
    out += ["", "## Generated files", ""]
    out += [f"- `{f['path']}` sha256 `{f['sha256'][:12]}`" for f in r.files]
    if readme:
        out += ["", "## Generated project README", "", readme]
    return "\n".join(out) + "\n"


def read_readme(db: Session, task_id: uuid.UUID) -> str | None:
    its = list(db.scalars(select(Iteration).where(Iteration.task_id == task_id)))
    if not its:
        return None
    last = max(its, key=lambda i: i.iteration_number)
    try:
        return workspace.read_file(workspace.log_dir(task_id, last.iteration_number), README_NAME)
    except (workspace.WorkspaceError, OSError):
        return None
