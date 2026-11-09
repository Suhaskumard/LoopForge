"""Explainer agent (Round 12): a plain-English "why did this fail and what should change" for a
FAILED or ESCALATED task. Like the Documentation agent it only runs after the verdict and can
never change it. Its input is the stored evidence, fenced as untrusted data.
"""

from app.agents.base import AgentContext, call_agent, wrap_untrusted
from app.schemas.advanced import ExplainOutput

NAME = "Explainer"

SYSTEM = """You are the Explainer agent of an autonomous software engineering platform.
A task's build-test-repair loop ended without being accepted. From the evidence below, explain
to a developer, in plain language, why it failed and what to change next.
Rules: use only the evidence; do not invent tests, files or results; be specific and short.
`retry_note` is a single instruction that will be handed to the Repair agent on the next attempt
(e.g. which behaviour to fix and how). Respond with JSON matching:
{"summary": str, "root_causes": [str, ...], "suggested_fix": str, "retry_note": str,
 "confidence": "low"|"medium"|"high"}."""


def run(ctx: AgentContext, evidence: list[str], requirement: str) -> ExplainOutput:
    """One model call; raises AgentFailure (from call_agent) if the model cannot answer."""
    return call_agent(
        ctx,
        agent_name=NAME,
        system=SYSTEM,
        user=(
            f"Requirement:\n{wrap_untrusted(requirement[:4000])}\n"
            f"Evidence:\n{wrap_untrusted(chr(10).join(f'- {e}' for e in evidence)[:12_000])}"
        ),
        response_model=ExplainOutput,
        input_summary=f"explain failure from {len(evidence)} facts",
    )
