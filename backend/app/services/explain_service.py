"""Round 12: explain why a task failed, and retry it with the suggested fix.

Two layers:
- an **evidence digest** built only from stored records (report_service), always available;
- an **AI narrative** from the Explainer agent when a real model answers. If the model fails (or
  the fake demo provider is in use, whose fixed script has no answer for this agent), the
  explanation is composed from the evidence instead, and labelled as such.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agents import explainer
from app.agents.base import AgentContext, AgentFailure
from app.config import settings
from app.database.models import CodeComment, Iteration, Task, TestResult
from app.schemas.advanced import Explanation
from app.services import report_service
from app.services.llm_client import LLMClient, LLMError
from app.utils.token_tracker import TokenTracker

log = logging.getLogger("loopforge.explain")

EXPLAINABLE = ("FAILED", "ESCALATED")


class ExplainError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _last_iteration(db: Session, task: Task) -> Iteration | None:
    return db.scalars(
        select(Iteration)
        .where(Iteration.task_id == task.id)
        .order_by(Iteration.iteration_number.desc())
    ).first()


def evidence(db: Session, task: Task) -> tuple[list[str], Any]:
    """Facts only, from the same records the Final Report uses."""
    report = report_service.build_report(db, task)
    fe = report.failure_explanation
    facts: list[str] = list(fe.what_failed) if fe else []
    last = _last_iteration(db, task)
    if last is not None:
        result = db.scalars(
            select(TestResult)
            .where(TestResult.iteration_id == last.id)
            .order_by(TestResult.created_at.desc())
        ).first()
        failures = (result.details or {}).get("failures", []) if result else []
        for f in failures[:6]:
            if isinstance(f, dict):
                msg = str(f.get("message", "")).splitlines()[0][:200] if f.get("message") else ""
                facts.append(f"Failing test {f.get('nodeid', '?')}: {msg}".rstrip(": "))
    if fe:
        for a in fe.repair_attempts[-4:]:
            files = f" (files: {', '.join(a.files[:4])})" if a.files else ""
            facts.append(
                f"Repair attempt [{a.failure_class or 'failure'}]: "
                f"{a.root_cause}{files} -> {a.outcome}"
            )
    return facts or ["The run stopped without recording any test or repair evidence."], fe


def _from_evidence(facts: list[str], fe: Any) -> dict[str, Any]:
    """A deterministic explanation: no model involved."""
    attempts = list(fe.repair_attempts) if fe else []
    causes = [a.root_cause for a in attempts if a.root_cause][-3:]
    failing = [f for f in facts if f.startswith("Failing test")][:3]
    next_steps = list(fe.next_steps) if fe else []
    root = (causes or [f for f in facts if not f.startswith("Repair attempt")][:3]) or facts[:1]
    repeated = len(set(causes)) < len(causes)
    summary = facts[0] if facts else "The run stopped before it was accepted."
    if repeated:
        summary += " The same cause came back after repair, so the requirement may be ambiguous."
    fix = next_steps[0] if next_steps else "Refine the requirement and run again."
    note_parts = []
    if failing:
        note_parts.append(
            "Make these pass: " + "; ".join(f.removeprefix("Failing test ") for f in failing)
        )
    if causes:
        note_parts.append(f"Earlier repairs tried: {causes[-1]}; take a different approach.")
    note = " ".join(note_parts) or fix
    return {
        "summary": summary[:600],
        "root_causes": [r[:300] for r in root][:5],
        "suggested_fix": fix[:800],
        "retry_note": note[:500],
        "confidence": "medium" if (failing or causes) else "low",
    }


def explain(db: Session, task: Task, llm: LLMClient | None) -> Explanation:
    if task.status not in EXPLAINABLE:
        raise ExplainError(
            f"only FAILED or ESCALATED tasks can be explained (this one is {task.status})"
        )
    last = _last_iteration(db, task)
    if last is None:
        raise ExplainError("this task never ran an iteration, so there is nothing to explain")
    facts, fe = evidence(db, task)
    body: dict[str, Any] | None = None
    source = "evidence"
    if llm is not None and settings.llm_provider != "fake":
        try:
            from app.services.run_service import total_tokens

            ctx = AgentContext(
                db=db, task=task, iteration=last, llm=llm,
                tracker=TokenTracker(settings.max_token_budget, used=total_tokens(db, task)),
            )  # fmt: skip
            body = explainer.run(ctx, facts, task.requirement).model_dump()
            source = "ai"
        except (AgentFailure, LLMError) as exc:
            log.warning("explainer fell back to the evidence: %s", exc)
            db.rollback()
            body = None
    if body is None:
        body = _from_evidence(facts, fe)
    out = Explanation(
        **body,
        source=source,
        evidence=facts[:20],
        iteration=last.iteration_number,
        created_at=_now(),
    )
    feedback = dict(last.feedback or {})
    feedback["explanation"] = out.model_dump(mode="json")
    last.feedback = feedback
    flag_modified(last, "feedback")
    db.commit()
    return out


def stored(db: Session, task: Task) -> Explanation | None:
    last = _last_iteration(db, task)
    raw = (last.feedback or {}).get("explanation") if last is not None else None
    return Explanation.model_validate(raw) if raw else None


def add_retry_note(db: Session, task: Task, user_id: Any) -> Explanation:
    """Hand the suggested fix to the Repair agent as an unresolved note (it reads those)."""
    exp = stored(db, task)
    if exp is None:
        raise ExplainError("explain the failure first")
    db.add(
        CodeComment(
            task_id=task.id, user_id=user_id, file_path="", line=None,
            body=f"Suggested fix from the failure analysis: {exp.retry_note}"[:2000],
            iteration_number=exp.iteration,
        )
    )  # fmt: skip
    db.commit()
    return exp
