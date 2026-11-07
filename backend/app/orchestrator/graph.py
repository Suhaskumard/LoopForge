"""LangGraph workflow: planner -> builder -> executor -> END, aborting deterministically on failure.

Routing is plain Python (spec principle 3). Phase 3 added the executor (sandboxed tests);
Phase 4 adds review/repair.
A MemorySaver checkpointer runs after every node; the persistent Postgres checkpointer arrives
with the resumable loop in Phase 4.
"""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents import coder, planner, verifier
from app.agents.base import AgentContext, AgentFailure
from app.execution.runner import CommandNotAllowed
from app.execution.sandbox import Sandbox, SandboxError
from app.orchestrator.state import LoopForgeState
from app.schemas.plan import ProjectPlan
from app.services import task_service
from app.services.task_service import TaskStatus


def _history(state: LoopForgeState, node: str, ok: bool, **extra: Any) -> list[dict[str, Any]]:
    return [*state["execution_history"], {"node": node, "ok": ok, **extra}]


def build_graph(ctx: AgentContext, sandbox: Sandbox) -> Any:
    def planner_node(state: LoopForgeState) -> dict[str, Any]:
        try:
            plan = planner.run(ctx, state["user_requirement"])
            task_service.transition(ctx.db, ctx.task, TaskStatus.GENERATING)
        except AgentFailure as exc:
            return {
                "error": str(exc),
                "escalate": exc.escalate,
                "status": "failed",
                "tokens_used": ctx.tracker.used,
                "execution_history": _history(state, "planner", False, error=str(exc)),
            }
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
            return {
                "error": str(exc),
                "escalate": exc.escalate,
                "status": "failed",
                "tokens_used": ctx.tracker.used,
                "execution_history": _history(state, "builder", False, error=str(exc)),
            }
        return {
            "generated_files": {w.path: str(w.artifact_id) for w in written},
            "tokens_used": ctx.tracker.used,
            "status": "generated",
            "execution_history": _history(state, "builder", True, files=len(written)),
        }

    def executor_node(state: LoopForgeState) -> dict[str, Any]:
        try:
            task_service.transition(ctx.db, ctx.task, TaskStatus.EXECUTING)
            summary = verifier.run(ctx, sandbox)
            task_service.transition(ctx.db, ctx.task, TaskStatus.TESTING)
        except (SandboxError, CommandNotAllowed) as exc:
            return {
                "error": f"sandbox execution failed: {exc}",
                "escalate": False,
                "status": "failed",
                "tokens_used": ctx.tracker.used,
                "execution_history": _history(state, "executor", False, error=str(exc)),
            }
        return {
            "test_results": summary.as_dict(),
            "tokens_used": ctx.tracker.used,
            "status": "tested",
            "execution_history": _history(
                state, "executor", True, passed=summary.passed, failed=summary.failed
            ),
        }

    def after_builder(state: LoopForgeState) -> str:
        return END if state["error"] else "executor"

    def after_planner(state: LoopForgeState) -> str:
        return END if state["error"] else "builder"

    graph = StateGraph(LoopForgeState)
    graph.add_node("planner", planner_node)
    graph.add_node("builder", builder_node)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", after_planner, {"builder": "builder", END: END})
    graph.add_node("executor", executor_node)
    graph.add_conditional_edges("builder", after_builder, {"executor": "executor", END: END})
    graph.add_edge("executor", END)
    return graph.compile(checkpointer=MemorySaver())
