# LoopForge — Architecture

LoopForge is a **modular monolith** (ADR-0001) of six layers; evaluation feeds decisions back to orchestration.

| Layer | Responsibility | Package / tech | Status |
|---|---|---|---|
| Presentation | Command center, task builder, live workflow, code/evaluation views, analytics, report | `frontend/` React + Vite | **Phase 5 ✔** |
| API | Auth, projects, tasks, events, health | `backend/app/api` FastAPI | **Phase 1 ✔** |
| Orchestration | Shared state, checkpoints, Decision Engine | `app/orchestrator` LangGraph | **Phase 4 ✔** feedback loop, Decision Engine, persistent checkpoints |
| Intelligence | Planner, Builder, Verifier, Repair, Reviewer, Documentation | `app/agents` | **Planner, Builder, Verifier, Repair, Reviewer ✔ (Phases 2–4)**; Documentation Phase 6 |
| Execution | Sandboxed code run, Pytest/Ruff/Bandit/Coverage | `app/execution`, `app/evaluation` | **Phase 3–4 ✔** |
| Persistence | Tasks, iterations, evidence, audit | `app/database` PostgreSQL | **Phase 1 ✔** |

## Phase 1 request path
`Client → RequestContextMiddleware (request-id, access log, security headers) → router → dependency (JWT + token_version check) → service (owner-scoped queries) → SQLAlchemy session → PostgreSQL`.

Errors from any layer leave through one envelope (`app/api/errors.py`): `{"error": {"code", "message", "request_id", "details?"}}`.

## Phase 2 workflow (`POST /tasks/{id}/start`)
```
PENDING ─start→ PLANNING ─Planner (LLM → ProjectPlan)→ GENERATING ─Builder (LLM → BuilderOutput)→ files in workspace
            any agent failure → FAILED   ·   token budget exhausted → ESCALATED   (never left half-way)
```
- `app/orchestrator/graph.py` — LangGraph `StateGraph(LoopForgeState)`: `planner → builder → executor → review → decide → (repair → executor …) | END`, deterministic routing, `orchestrator/decision.py` (Decision Engine, no LLM) and a persistent SQLite/Postgres checkpointer (ADR-0009).
- `app/agents/base.py::call_agent` — wraps each LLM call: `agent_runs` row (status, tokens, duration), schema validation, **one** corrective retry, `agent_output_rejected` audit events, token budget check.
- `app/services/llm_client.py` — `OpenAIClient` / `FakeLLMClient` behind one protocol (ADR-0007).
- `app/services/workspace.py` — `<WORKSPACE_ROOT>/<task_id>/iter_<n>/`; path confinement, no symlinks/junctions, validate-all-then-write, atomic writes, sha256 `artifacts` rows.
- `app/demo/employee_management.py` — canned, *working* demo plan + project for deterministic tests (`LLM_PROVIDER=fake`).

## Phase 5 — interface and analytics
- `services/analytics_service.py` is the single owner of every KPI formula (cancelled excluded from success rate; latest `test_results` row per iteration, so no double counting; cost = tokens × `COST_PER_1K_TOKENS`, an *estimate*).
- `services/event_stream.py` + `api/ws.py` stream spec §8.2 events from database rows (ADR-0010).
- `frontend/`: seven screens (Command Center, Task Creation, Live Workflow with React Flow, Code Workspace with diff of any two iterations, Evaluation Center, Loop Analytics, Final Report). `make ui-demo` + `npm run dev` runs it with a scripted loop, no API key or Docker.

## Phase 6 - hardening, evaluation, release
- `agents/documenter.py` + `services/report_service.py`: the final report is deterministic from stored records; the Documentation Agent (after a terminal state only) adds a README and can never change a verdict.
- Budgets: per-task `token_budget` / `max_cost` tighten (never loosen) the server limits; the Decision Engine escalates on the cost cap.
- Human approval: `plan_gate` / `repair_gate` graph nodes use LangGraph `interrupt()`; status `AWAITING_APPROVAL` (ADR-0013).
- `utils/redact.py` scrubs secrets from prompts, summaries, audit events and stored logs.
- `orchestrator/loop_config.py`: E1-E3 and A1-A4 are switches on the one production loop. `benchmarks/` holds 30 tasks with hidden tests, `run_benchmarks.py` and `analyze.py` (ADR-0012).

## Phase 7 - scale-out
- `RUN_MODE=queue` makes the API enqueue `jobs` rows instead of running the loop in-process; `python -m app.worker` (any number of them, `docker compose --profile workers up`) claims and runs them. Default `inline` is unchanged.
- `services/lease_service.py`: per-task `run_leases` row with heartbeat (`LEASE_TTL_SECONDS`); a second process cannot drive a task a live process holds, and a dead owner's task is taken over after expiry. `job_service.recover` re-queues resumes for orphaned work.
- `TRUSTED_PROXY_COUNT` for correct login rate-limit keys behind proxies. Details and limits: ADR-0014.
- `make gate7` = Phase 6 gate + the Phase 7 tests.

## Phase 10 - organizations, roles, SSO, audit, quotas
- **Multi-tenant**: every project/task belongs to an organization; users can be in several and pick one (`X-Org-Id`, org switcher in the UI). Roles `viewer < developer < approver < admin`, read from the database per request. Non-members get 404 (path) / 403 (header). Registering creates a personal organization; migration `0006` moves existing data into one.
- **Audit log** (`audit_log`): who did what, redacted, **append-only via DB triggers**; admins read it at `GET /orgs/{id}/audit` and in the Admin page.
- **Quotas** per organization and month (tokens, tasks) enforced at task create and run start, and the run is capped at what is left. **Data**: retention days, zip export, confirmed delete-all.
- **OIDC SSO** (generic; PKCE + state + nonce, ID token verified against JWKS): set `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`; password login stays. New dependency: `cryptography`. Details, threat decisions and **known limits**: ADR-0017. `make gate10`.

## Phase 9 - smarter loop
- Repair now (1) is told the **failure class** (syntax / import / environment / test_wrong / logic, `evaluation/failure_class.py`) with a matching strategy, (2) sees only the **relevant files in full** plus outlines of the rest (`agents/repair_context.py`), (3) has any patch that **weakens tests** rejected - fewer tests or assertions, added skip/xfail (`evaluation/test_guard.py`), and (4) is shown **similar repairs that resolved** failures in the same owner's other tasks.
- **Per-agent models**: `MODEL_PLANNER`, `MODEL_BUILDER`, `MODEL_REPAIR`, `MODEL_REVIEWER`, `MODEL_DOCUMENTATION` (empty = `OPENAI_MODEL`); the model used is stored on each `agent_runs` row.
- Each feature is a `LoopConfig` switch, on in E3: presets `P0` (all Phase 9 off) and `P1`-`P4` (one off) support leave-one-out ablation; `analyze.py` prints a Phase 9 table and says "not distinguishable from noise" when intervals overlap. **No benefit is claimed: it is To be measured** with a real model. Migration `0005`. ADR-0016. `make gate9`.

## Phase 8 - existing repositories and JavaScript
- A task can start from a **zip upload** (`source_type=zip`, then `POST /tasks/{id}/source`) or a public **https git URL** (cloned in the run/worker). The repo becomes iteration 0; `execution/languages.py` profiles (Python, JavaScript/TypeScript with Jest + ESLint) drive tests, lint, dependency policy and the sandbox image.
- Repos are untrusted: size/file/depth limits, zip-slip/symlink/zip-bomb defences, secret-bearing files excluded from every prompt. Details and limits: ADR-0015.
- `benchmarks/tasks_phase8/`: 10 repo-input + 10 JavaScript tasks; `python benchmarks/validate_phase8.py` (JS needs Jest via `LOOPFORGE_JEST`, otherwise SKIP). `make gate8`.
- Node sandbox image: `docker build -t loopforge-sandbox-node -f backend/sandbox/node/Dockerfile backend/sandbox` (not built in the dev environment).

## Key design rules (from the spec)
1. Evidence over assertion · 2. Maker ≠ checker · 3. Deterministic control (no LLM in the loop controller) · 4. Revalidate everything · 5. Bounded by default · 6. Isolation first · 7. Full traceability · 8. Loop before interface.

## Phase 1 specifics
- **State machine**: `app/services/task_service.py` (`ALLOWED_TRANSITIONS`); every change writes an `audit_events` row; transitions take a row lock (`SELECT … FOR UPDATE`, Postgres).
- **Optimistic concurrency**: `version` column via SQLAlchemy `version_id_col`; exposed as `ETag`, honoured via `If-Match` (412 on mismatch); lost-update races surface as 409.
- **Sessions**: 15-min access JWT carrying `tv` (token_version) + rotating refresh tokens (ADR-0006, `docs/security_model.md`).
- **Config**: `app/config.py` (pydantic-settings); production refuses a weak `JWT_SECRET`.

## Directory map
See `README.md`; layout follows spec §10.
