"""LangGraph workflow (spec §5): the feedback loop.

    planner -> builder -> executor -> review -> decide --retry--> repair -> executor ...
                                                  \\--complete/escalate/stop--> END

Routing is plain Python and the Decision Engine is deterministic (principle 3, ADR-0004).
A persistent checkpointer saves state after every node. Nodes are idempotent: each derives the
current iteration from the state, looks in the database before redoing work, and only moves the
task status when it is not already there, so re-running a node after a crash is safe.
"""

import time
from dataclasses import asdict
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select

from app.agents import coder, planner, repair, reviewer, verifier
from app.agents.base import AgentContext, AgentFailure
from app.config import settings
from app.database.models import (
    ApprovalRequest,
    AuditEvent,
    Iteration,
    RepairHistory,
    TestResult,
)
from app.evaluation.classifier import (
    build_failure_report,
    classify_execution,
    classify_quality,
    classify_requirements,
)
from app.evaluation.quality import run_quality
from app.evaluation.test_runner import TestFailure, TestSummary
from app.execution.languages import get_profile
from app.execution.runner import CommandNotAllowed
from app.execution.sandbox import Sandbox, SandboxError
from app.orchestrator.checkpoint import get_checkpointer
from app.orchestrator.decision import Decision, Limits, evaluate_iteration, failure_fingerprint
from app.orchestrator.loop_config import E3, LoopConfig
from app.orchestrator.state import LoopForgeState
from app.schemas.plan import ProjectPlan
from app.services import notification_service, task_service, workspace
from app.services.task_service import TaskStatus
from app.utils.redact import redact


def _history(state: LoopForgeState, node: str, ok: bool, **extra: Any) -> list[dict[str, Any]]:
    return [*state["execution_history"], {"node": node, "ok": ok, **extra}]


def limits_from_settings(task: Any = None, config: LoopConfig = E3) -> Limits:
    """Server limits, tightened (never loosened) by the task's own budgets."""
    budget = settings.max_token_budget
    if task is not None and task.token_budget:
        budget = min(budget, task.token_budget)
    return Limits(
        max_tokens=budget,
        max_task_seconds=settings.max_task_duration_seconds,
        max_attempts_per_failure=(
            settings.max_attempts_per_failure if config.adaptive_retry else 10**9
        ),
        max_cost=getattr(task, "max_cost", None),
        cost_per_1k_tokens=settings.cost_per_1k_tokens,
    )


def _tests_view(summary: TestSummary) -> dict[str, Any]:
    """The shape the Decision Engine consumes (spec §5.3)."""
    return {
        "total_tests": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "skipped": summary.skipped,
        "coverage": summary.coverage,
        "timed_out": summary.timed_out,
        "partial": summary.partial,
        "failures": [asdict(f) for f in summary.failures],
    }


def _summary_from_row(row: TestResult) -> TestSummary:
    d = row.details
    return TestSummary(
        total=row.total_tests,
        passed=row.passed,
        failed=row.failed,
        skipped=row.skipped,
        exit_code=d.get("exit_code", 0),
        timed_out=d.get("timed_out", False),
        report_found=d.get("report_found", False),
        coverage=row.coverage,
        partial=d.get("partial", False),
        duration_seconds=d.get("duration_seconds", 0.0),
        failures=[TestFailure(**f) for f in d.get("failures", [])],
    )


def build_graph(
    ctx: AgentContext,
    sandbox: Sandbox,
    limits: Limits | None = None,
    config: LoopConfig = E3,
) -> Any:
    limits = limits or limits_from_settings(ctx.task, config)
    db, task = ctx.db, ctx.task

    # ---- helpers ------------------------------------------------------------------------
    def bind(number: int) -> Iteration:
        it = db.scalars(
            select(Iteration).where(
                Iteration.task_id == task.id, Iteration.iteration_number == number
            )
        ).first()
        if it is None:
            raise RuntimeError(f"iteration {number} not found for task {task.id}")
        ctx.iteration = it
        return it

    def cancelled() -> bool:
        db.refresh(task)
        return task.status == TaskStatus.CANCELLED.value

    def move(target: TaskStatus, *, only_from: set[TaskStatus]) -> None:
        """Idempotent status change: no-op when already there, error if from an odd state."""
        current = TaskStatus(task.status)
        if current == target:
            return
        if current in only_from:
            task_service.transition(db, task, target)
            return
        raise RuntimeError(f"unexpected task status {current.value} while moving to {target.value}")

    def audit(event: str, data: dict[str, Any]) -> None:
        db.add(AuditEvent(task_id=task.id, event_type=event, event_data=data))
        db.commit()

    def fail(
        state: LoopForgeState, node: str, exc: Exception, *, escalate: bool = False
    ) -> dict[str, Any]:
        return {
            "error": str(exc),
            "escalate": escalate,
            "status": "failed",
            "tokens_used": ctx.tracker.used,
            "execution_history": _history(state, node, False, error=str(exc)),
        }

    def stopped(state: LoopForgeState, node: str) -> dict[str, Any]:
        return {
            "status": "cancelled",
            "decision": Decision.STOP.value,
            "tokens_used": ctx.tracker.used,
            "execution_history": _history(state, node, True, cancelled=True),
        }

    # ---- nodes --------------------------------------------------------------------------
    def planner_node(state: LoopForgeState) -> dict[str, Any]:
        try:
            plan = planner.run(ctx, state["user_requirement"])
            move(TaskStatus.GENERATING, only_from={TaskStatus.PLANNING})
        except AgentFailure as exc:
            return fail(state, "planner", exc, escalate=exc.escalate)
        return {
            "project_plan": plan.model_dump(),
            "tokens_used": ctx.tracker.used,
            "status": "generating",
            "execution_history": _history(state, "planner", True),
        }

    def builder_node(state: LoopForgeState) -> dict[str, Any]:
        plan = ProjectPlan.model_validate(state["project_plan"])
        try:
            written = coder.run(ctx, plan)
        except AgentFailure as exc:
            return fail(state, "builder", exc, escalate=exc.escalate)
        audit("files_generated", {"count": len(written)})
        return {
            "generated_files": {w.path: str(w.artifact_id) for w in written},
            "tokens_used": ctx.tracker.used,
            "status": "generated",
            "execution_history": _history(state, "builder", True, files=len(written)),
        }

    def executor_node(state: LoopForgeState) -> dict[str, Any]:
        if cancelled():
            return stopped(state, "executor")
        it = bind(state["iteration"])
        try:
            if task.status in (TaskStatus.GENERATING.value, TaskStatus.REPAIRING.value):
                task_service.transition(db, task, TaskStatus.EXECUTING)
            row = db.scalars(select(TestResult).where(TestResult.iteration_id == it.id)).first()
            summary = (
                _summary_from_row(row)
                if row
                else verifier.run(
                    ctx,
                    sandbox,
                    affected_first=config.affected_tests_first,
                    changed_line_cov=config.changed_line_coverage,
                    mutation_check=config.test_mutation_check,
                )
            )
            if row is None:
                audit(
                    "tests_executed",
                    {
                        "iteration": it.iteration_number,
                        "total": summary.total,
                        "passed": summary.passed,
                        "failed": summary.failed,
                        "skipped": summary.skipped,
                        "timed_out": summary.timed_out,
                    },
                )
            if cancelled():
                return stopped(state, "executor")
            if task.status == TaskStatus.EXECUTING.value:
                task_service.transition(db, task, TaskStatus.TESTING)
        except (SandboxError, CommandNotAllowed) as exc:
            return fail(state, "executor", RuntimeError(f"sandbox execution failed: {exc}"))
        view = _tests_view(summary)
        return {
            "test_results": view,
            "tokens_used": ctx.tracker.used,
            "status": "tested",
            "execution_history": _history(
                state,
                "executor",
                True,
                iteration=it.iteration_number,
                passed=summary.passed,
                failed=summary.failed,
            ),
        }

    def review_node(state: LoopForgeState) -> dict[str, Any]:
        if cancelled():
            return stopped(state, "review")
        it = bind(state["iteration"])
        plan = ProjectPlan.model_validate(state["project_plan"])
        row = db.scalars(select(TestResult).where(TestResult.iteration_id == it.id)).first()
        if row is None:
            return fail(state, "review", RuntimeError("no test results to review"))
        summary = _summary_from_row(row)
        try:
            move(TaskStatus.REVIEWING, only_from={TaskStatus.TESTING})
            if "review" in it.feedback:  # resumed after the review was already stored
                review, quality = it.feedback["review"], it.feedback["quality"]
            else:
                src = workspace.iteration_dir(task.id, it.iteration_number)
                qrep = run_quality(
                    sandbox,
                    src,
                    workspace.out_dir(task.id, it.iteration_number),
                    settings.max_execution_seconds,
                    get_profile(task.project.language),
                )
                if config.reviewer_enabled:
                    review = reviewer.run(ctx, plan, summary, qrep)
                else:
                    review = reviewer.run_tests_only(ctx, plan, summary, qrep)
                if not config.requirement_verification:
                    review = {**review, "unverified_mandatory": 0}  # ablation A3
                quality = qrep.as_dict()
                it.feedback = {**it.feedback, "review": review, "quality": quality}
                it.quality_score = float(review["quality_score"])
                db.commit()
        except (SandboxError, CommandNotAllowed) as exc:
            return fail(state, "review", RuntimeError(f"sandbox execution failed: {exc}"))
        except AgentFailure as exc:
            return fail(state, "review", exc, escalate=exc.escalate)
        return {
            "review_results": review,
            "quality": quality,
            "quality_score": float(review["quality_score"]),
            "tokens_used": ctx.tracker.used,
            "status": "reviewed",
            "execution_history": _history(
                state, "review", True, critical=review["critical_issues"],
                high=review["unapproved_high_severity"],
            ),
        }  # fmt: skip

    def decide_node(state: LoopForgeState) -> dict[str, Any]:
        it = bind(state["iteration"])
        tests, review = state["test_results"], state["review_results"]
        eval_state: dict[str, Any] = {
            **state,
            "status": "cancelled" if cancelled() else state["status"],
        }
        decision = evaluate_iteration(eval_state, limits)
        fps = list(state["failure_fingerprints"])
        fp = failure_fingerprint(tests, review)
        _close_repair_record(it, tests)

        if decision is Decision.RETRY:
            fps.append(fp)
        elif decision is Decision.COMPLETE:
            task_service.transition(db, task, TaskStatus.COMPLETED)
        elif decision is Decision.ESCALATE:
            task_service.transition(db, task, TaskStatus.ESCALATED)
        it.status = {
            Decision.COMPLETE: "accepted",
            Decision.RETRY: "failed_tests" if tests["failed"] else "rejected",
            Decision.ESCALATE: "escalated",
            Decision.STOP: "cancelled",
        }[decision]
        it.completed_at = _now()
        it.feedback = {
            **it.feedback,
            "decision": {"action": decision.value, "fingerprint": fp},
            "tests": {
                k: tests[k] for k in ("total_tests", "passed", "failed", "skipped", "coverage")
            },
        }
        db.commit()
        audit(
            "decision",
            {
                "iteration": it.iteration_number,
                "action": decision.value,
                "failed": tests["failed"],
                "passed": tests["passed"],
                "fingerprint": fp[:12],
            },
        )
        return {
            "decision": decision.value,
            "failure_fingerprints": fps,
            "best_test_count": state["best_test_count"]
            if tests.get("partial")
            else max(state["best_test_count"], tests["total_tests"]),
            "status": "cancelled" if decision is Decision.STOP else decision.value,
            "final_report": _final_report(state, it, decision),
            "tokens_used": ctx.tracker.used,
            "execution_history": _history(state, "decide", True, decision=decision.value),
        }

    def repair_node(state: LoopForgeState) -> dict[str, Any]:
        if cancelled():
            return stopped(state, "repair")
        it = bind(state["iteration"])
        try:
            move(TaskStatus.REPAIRING, only_from={TaskStatus.REVIEWING})
            report = _failure_report(state)
            new_it = repair.run(
                ctx,
                report,
                state["failure_fingerprints"][-1],
                memory=config.memory_enabled,
                failure_routing=config.failure_routing,
                targeted_context=config.targeted_context,
                test_guard=config.test_guard,
                history_retrieval=config.history_retrieval,
                memory_expiry=config.memory_expiry,
                patch_edits=config.patch_edits,
            )
        except AgentFailure as exc:
            return fail(state, "repair", exc, escalate=exc.escalate)
        ctx.iteration = new_it
        audit(
            "repair_applied",
            {
                "from_iteration": it.iteration_number,
                "to_iteration": new_it.iteration_number,
                "files": new_it.feedback["repair"]["files_modified"],
            },
        )
        return {
            "iteration": new_it.iteration_number,
            "iteration_in_run": state["iteration_in_run"] + 1,
            "failure_report": report,
            "decision": None,
            "tokens_used": ctx.tracker.used,
            "status": "repaired",
            "execution_history": _history(
                state, "repair", True, to_iteration=new_it.iteration_number
            ),
        }

    # ---- human approval gates (spec 13.2) --------------------------------------------------
    def gate(kind: str, number: int, summary: str, detail: dict[str, Any]) -> bool:
        """True when the loop may continue. A pending request pauses the run (LangGraph interrupt):
        the checkpoint keeps the state, the task waits in AWAITING_APPROVAL, and approving resumes
        from this node. Idempotent - a request is created once per (task, kind, iteration)."""
        req = db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.task_id == task.id,
                ApprovalRequest.kind == kind,
                ApprovalRequest.iteration_number == number,
            )
        ).first()
        if req is None:
            req = ApprovalRequest(
                task_id=task.id,
                kind=kind,
                iteration_number=number,
                summary=redact(summary)[:1000],
                detail=detail,
                resume_status=task.status,
            )
            db.add(req)
            db.commit()
            audit("approval_requested", {"kind": kind, "iteration": number, "id": str(req.id)})
            notification_service.notify_safely(
                db, task.project.org_id, "approval.needed", f"Approval needed: {req.summary}"[:200],
                {"task_id": str(task.id), "approval_id": str(req.id), "kind": kind},
                roles=("approver", "admin"), dedupe_key=f"approval:{req.id}",
            )  # fmt: skip
        db.refresh(req)
        if req.status == "pending":
            if task.status != TaskStatus.AWAITING_APPROVAL.value:
                task_service.transition(db, task, TaskStatus.AWAITING_APPROVAL)
            interrupt({"approval_id": str(req.id), "kind": kind})
            db.refresh(req)
        return req.status == "approved"

    def plan_gate_node(state: LoopForgeState) -> dict[str, Any]:
        if not (config.approvals_enabled and task.require_plan_approval):
            return {}
        plan = state["project_plan"]
        ok = gate(
            "plan",
            state["iteration"],
            f"Review the plan for {plan.get('project_name', 'the project')}",
            {"files": [f["path"] for f in plan.get("files", [])]},
        )
        if not ok:
            return fail(state, "plan_gate", RuntimeError("plan rejected by a human"), escalate=True)
        return {"execution_history": _history(state, "plan_gate", True)}

    def repair_gate_node(state: LoopForgeState) -> dict[str, Any]:
        it = bind(state["iteration"])
        files = it.feedback.get("repair", {}).get("files_modified", [])
        if not config.approvals_enabled or len(files) <= settings.approval_max_repair_files:
            return {}
        ok = gate(
            "large_repair",
            it.iteration_number,
            f"Repair modifies {len(files)} files (limit {settings.approval_max_repair_files})",
            {"files": files},
        )
        if not ok:
            return fail(
                state, "repair_gate", RuntimeError("repair rejected by a human"), escalate=True
            )
        return {"execution_history": _history(state, "repair_gate", True)}

    # ---- helpers needing state ----------------------------------------------------------
    def _failure_report(state: LoopForgeState) -> dict[str, Any]:
        tests, review, quality = state["test_results"], state["review_results"], state["quality"]
        return build_failure_report(
            classify_execution(tests["failures"]),
            classify_quality(quality["ruff"], quality["bandit_high"], tests.get("coverage")),
            classify_requirements(review["acceptance_criteria"]),
        )

    def _close_repair_record(it: Iteration, tests: dict[str, Any]) -> None:
        """Record whether the repair that produced this iteration actually fixed things."""
        rec = db.scalars(select(RepairHistory).where(RepairHistory.iteration_id == it.id)).first()
        if rec is None or rec.outcome != "applied":
            return
        rec.outcome = "resolved" if tests["failed"] == 0 else "unresolved"
        rec.tests_executed = [f"full suite: {tests['passed']}/{tests['total_tests']} passed"]
        rec.regression_status = "full suite re-run"
        db.commit()

    def _final_report(state: LoopForgeState, it: Iteration, decision: Decision) -> dict[str, Any]:
        return {
            "decision": decision.value,
            "iterations_in_run": state["iteration_in_run"],
            "last_iteration": it.iteration_number,
            "tests": {k: state["test_results"][k] for k in ("total_tests", "passed", "failed")},
            "tokens_used": ctx.tracker.used,
            "seconds": round(time.time() - state["started_at"], 1),
        }

    # ---- routing (plain Python) ---------------------------------------------------------
    def go(next_node: str) -> Any:
        def route(state: LoopForgeState) -> str:
            if state["error"] or state["status"] == "cancelled":
                return END
            return next_node

        return route

    def after_decide(state: LoopForgeState) -> str:
        return "repair" if state["decision"] == Decision.RETRY.value else END

    graph = StateGraph(LoopForgeState)
    for name, fn in (
        ("planner", planner_node),
        ("plan_gate", plan_gate_node),
        ("builder", builder_node),
        ("executor", executor_node),
        ("review", review_node),
        ("decide", decide_node),
        ("repair", repair_node),
        ("repair_gate", repair_gate_node),
    ):
        graph.add_node(name, fn)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", go("plan_gate"), {"plan_gate": "plan_gate", END: END})
    graph.add_conditional_edges("plan_gate", go("builder"), {"builder": "builder", END: END})
    graph.add_conditional_edges("builder", go("executor"), {"executor": "executor", END: END})
    graph.add_conditional_edges("executor", go("review"), {"review": "review", END: END})
    graph.add_conditional_edges("review", go("decide"), {"decide": "decide", END: END})
    graph.add_conditional_edges("decide", after_decide, {"repair": "repair", END: END})
    graph.add_conditional_edges(
        "repair", go("repair_gate"), {"repair_gate": "repair_gate", END: END}
    )
    graph.add_conditional_edges("repair_gate", go("executor"), {"executor": "executor", END: END})
    # First use of the Postgres checkpointer runs CREATE INDEX CONCURRENTLY, which waits for every
    # open transaction - including this session's own read transaction. End it first.
    db.commit()
    return graph.compile(checkpointer=get_checkpointer(db.get_bind().engine.url))


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(tzinfo=None)
