# LoopForge

Autonomous, feedback-driven AI software-engineering platform: natural-language requirement → plan → generated Python → sandboxed tests → independent review → deterministic retry/accept/escalate, until measurable acceptance criteria are met.

**Status:** Phases 1–6 built (foundation, agents, sandbox, feedback loop, dashboard + analytics, hardening + evaluation harness). **No benchmark result has been measured yet** (needs an API key): see `docs/evaluation_report.md`. Roadmap: spec phases 1–6, then post-MVP phases 7–10 (scale, languages/repos, advanced intelligence, enterprise).

## Quick start
```bash
bash scripts/setup.sh                      # venv, deps, .env, Postgres, migrations
cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --reload   # http://localhost:8000/docs
make gate                                  # Phase 1: lint + mypy --strict + tests + migration checks
make gate2                                 # Phase 1 + Phase 2 gate and the evidence demo
make demo2                                 # Phase 2 exit-gate evidence, no API key needed
WITH_PG=1 make gate                        # ...and the suite on Postgres (docker compose up -d db first)
```
make gate5                                 # everything above + frontend checks + KPI-vs-DB demo
make gate6                                 # everything + 30 benchmark tasks + spec 15.1 acceptance checklist + harness check
make acceptance                            # the 15.1 checklist with evidence (PASS / SKIP / FAIL)
make demo-final                            # clean-environment rehearsal in a fresh virtualenv
make ui-demo                               # scripted API on :8000, then `cd frontend && npm install && npm run dev` -> http://localhost:5173
Docs: `docs/architecture.md`, `api_documentation.md`, `database_schema.md`, `security_model.md`, `docs/adr/`.

## Phase 2 configuration
`LLM_PROVIDER=openai|fake`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `WORKSPACE_ROOT`, `LLM_MAX_RETRIES`, `LLM_TIMEOUT_SECONDS`, `MAX_TOKEN_BUDGET`. With `LLM_PROVIDER=fake` the built-in employee-management demo is served (rejected in production). Live smoke test: `cd backend && pytest -m live` (needs a key).
