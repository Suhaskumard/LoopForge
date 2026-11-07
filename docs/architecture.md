# LoopForge — Architecture

LoopForge is a **modular monolith** (ADR-0001) of six layers; evaluation feeds decisions back to orchestration.

| Layer | Responsibility | Package / tech | Status |
|---|---|---|---|
| Presentation | Task builder, workflow viewer, analytics | `frontend/` React + Vite | Phase 5 |
| API | Auth, projects, tasks, events, health | `backend/app/api` FastAPI | **Phase 1 ✔** |
| Orchestration | Shared state, checkpoints, Decision Engine | `app/orchestrator` LangGraph | Phase 2/4 |
| Intelligence | Planner, Builder, Verifier, Repair, Reviewer, Documentation | `app/agents` | Phase 2–6 |
| Execution | Sandboxed code run, Pytest/Ruff/Bandit/Coverage | `app/execution`, `app/evaluation` | Phase 3 |
| Persistence | Tasks, iterations, evidence, audit | `app/database` PostgreSQL | **Phase 1 ✔** |

## Phase 1 request path
`Client → RequestContextMiddleware (request-id, access log, security headers) → router → dependency (JWT + token_version check) → service (owner-scoped queries) → SQLAlchemy session → PostgreSQL`.

Errors from any layer leave through one envelope (`app/api/errors.py`): `{"error": {"code", "message", "request_id", "details?"}}`.

## Key design rules (from the spec)
1. Evidence over assertion · 2. Maker ≠ checker · 3. Deterministic control (no LLM in the loop controller) · 4. Revalidate everything · 5. Bounded by default · 6. Isolation first · 7. Full traceability · 8. Loop before interface.

## Phase 1 specifics
- **State machine**: `app/services/task_service.py` (`ALLOWED_TRANSITIONS`); every change writes an `audit_events` row; transitions take a row lock (`SELECT … FOR UPDATE`, Postgres).
- **Optimistic concurrency**: `version` column via SQLAlchemy `version_id_col`; exposed as `ETag`, honoured via `If-Match` (412 on mismatch); lost-update races surface as 409.
- **Sessions**: 15-min access JWT carrying `tv` (token_version) + rotating refresh tokens (ADR-0006, `docs/security_model.md`).
- **Config**: `app/config.py` (pydantic-settings); production refuses a weak `JWT_SECRET`.

## Directory map
See `README.md`; layout follows spec §10.
