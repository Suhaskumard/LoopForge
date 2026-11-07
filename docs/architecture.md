# LoopForge — Architecture

LoopForge is a **modular monolith** (ADR-0001) of six layers; evaluation feeds decisions back to orchestration.

| Layer | Responsibility | Package / tech | Status |
|---|---|---|---|
| Presentation | Task builder, workflow viewer, analytics | `frontend/` React + Vite | Phase 5 |
| API | Auth, projects, tasks, events, health | `backend/app/api` FastAPI | **Phase 1 ✔** |
| Orchestration | Shared state, checkpoints, Decision Engine | `app/orchestrator` LangGraph | **Phase 2 ✔** (planner→builder); Decision Engine Phase 4 |
| Intelligence | Planner, Builder, Verifier, Repair, Reviewer, Documentation | `app/agents` | **Planner + Builder ✔ (Phase 2)**; rest Phase 3–6 |
| Execution | Sandboxed code run, Pytest/Ruff/Bandit/Coverage | `app/execution`, `app/evaluation` | Phase 3 |
| Persistence | Tasks, iterations, evidence, audit | `app/database` PostgreSQL | **Phase 1 ✔** |

## Phase 1 request path
`Client → RequestContextMiddleware (request-id, access log, security headers) → router → dependency (JWT + token_version check) → service (owner-scoped queries) → SQLAlchemy session → PostgreSQL`.

Errors from any layer leave through one envelope (`app/api/errors.py`): `{"error": {"code", "message", "request_id", "details?"}}`.

## Phase 2 workflow (`POST /tasks/{id}/start`)
```
PENDING ─start→ PLANNING ─Planner (LLM → ProjectPlan)→ GENERATING ─Builder (LLM → BuilderOutput)→ files in workspace
            any agent failure → FAILED   ·   token budget exhausted → ESCALATED   (never left half-way)
```
- `app/orchestrator/graph.py` — LangGraph `StateGraph(LoopForgeState)`: `planner → builder → END`, deterministic conditional edge to END on failure, `MemorySaver` checkpointer (Postgres checkpointer lands in Phase 4).
- `app/agents/base.py::call_agent` — wraps each LLM call: `agent_runs` row (status, tokens, duration), schema validation, **one** corrective retry, `agent_output_rejected` audit events, token budget check.
- `app/services/llm_client.py` — `OpenAIClient` / `FakeLLMClient` behind one protocol (ADR-0007).
- `app/services/workspace.py` — `<WORKSPACE_ROOT>/<task_id>/iter_<n>/`; path confinement, no symlinks/junctions, validate-all-then-write, atomic writes, sha256 `artifacts` rows.
- `app/demo/employee_management.py` — canned, *working* demo plan + project for deterministic tests (`LLM_PROVIDER=fake`).

## Key design rules (from the spec)
1. Evidence over assertion · 2. Maker ≠ checker · 3. Deterministic control (no LLM in the loop controller) · 4. Revalidate everything · 5. Bounded by default · 6. Isolation first · 7. Full traceability · 8. Loop before interface.

## Phase 1 specifics
- **State machine**: `app/services/task_service.py` (`ALLOWED_TRANSITIONS`); every change writes an `audit_events` row; transitions take a row lock (`SELECT … FOR UPDATE`, Postgres).
- **Optimistic concurrency**: `version` column via SQLAlchemy `version_id_col`; exposed as `ETag`, honoured via `If-Match` (412 on mismatch); lost-update races surface as 409.
- **Sessions**: 15-min access JWT carrying `tv` (token_version) + rotating refresh tokens (ADR-0006, `docs/security_model.md`).
- **Config**: `app/config.py` (pydantic-settings); production refuses a weak `JWT_SECRET`.

## Directory map
See `README.md`; layout follows spec §10.
