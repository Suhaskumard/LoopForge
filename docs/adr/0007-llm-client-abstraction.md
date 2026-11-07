# ADR-0007: LLM client abstraction, structured output, and agent safety rails

Status: accepted (Phase 2)

## Context
Agents must produce machine-checkable output, never be trusted blindly, and be testable without an
API key, network or spend. The spec forbids silent acceptance of malformed output (§11.2 gate),
requires token accounting (§5.1) and treats code/README/requirement text as untrusted (§13.2).

## Decision
1. **`LLMClient` protocol** (`complete_json(system, user, response_model) -> LLMResult`). Implementations:
   `OpenAIClient` (real), `FakeLLMClient` (deterministic replay; records calls; non-zero token estimates).
   The agents and orchestrator never import the OpenAI SDK.
2. **Structured output only.** Every agent call names a strict Pydantic model (`extra="forbid"`).
   Output is validated, never coerced. Path rules (relative, no `..`/drive/UNC/hidden, extension allowlist)
   live in the schema, and are re-enforced by the workspace layer (defence in depth).
3. **Retry policy is split by responsibility.** The client retries *transport* faults only (rate limit,
   connection, timeout, 5xx) with capped exponential backoff and never retries 4xx or invalid output.
   The agent layer owns the *content* retry: exactly **one** corrective retry that feeds the validation
   error back to the model; after that the agent fails. Every rejection writes an `agent_output_rejected`
   audit event.
4. **Untrusted data fencing.** User/repo text is wrapped in `<untrusted_input>` delimiters (spoofed
   delimiters neutralised) and a fixed security policy heads every system prompt.
5. **Budget is backend-enforced.** `TokenTracker` is checked after every call; exhaustion stops the task
   as `ESCALATED` (not `FAILED`) and persists nothing from the over-budget call.
6. **Failure never strands a task.** Agent failure -> FAILED/ESCALATED + `run_failed` audit event;
   unexpected exceptions are caught, logged, and surfaced without internal detail.
7. **Provider selection** via `LLM_PROVIDER=openai|fake`; `fake` is rejected in production.

## Consequences
- The whole platform (including Phase 4's loop) can be tested deterministically and for free.
- Model quality on real tasks is a separate, measured question (Phase 6 benchmark); the optional
  `pytest -m live` smoke test checks wiring only.
- A model that obeys an injected instruction still cannot write outside the workspace: the schema and
  the workspace both refuse the path, and the Builder has no shell.
