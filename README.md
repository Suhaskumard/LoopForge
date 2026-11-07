# LoopForge

Autonomous, feedback-driven AI software-engineering platform: natural-language requirement → plan → generated Python → sandboxed tests → independent review → deterministic retry/accept/escalate, until measurable acceptance criteria are met.

**Status:** Phase 1 (Foundation) complete. Roadmap: spec phases 1–6, then post-MVP phases 7–10 (scale, languages/repos, advanced intelligence, enterprise).

## Quick start
```bash
bash scripts/setup.sh                      # venv, deps, .env, Postgres, migrations
cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --reload   # http://localhost:8000/docs
make gate                                  # lint + mypy --strict + tests + migration checks
WITH_PG=1 make gate                        # ...and the suite on Postgres (docker compose up -d db first)
```
Docs: `docs/architecture.md`, `api_documentation.md`, `database_schema.md`, `security_model.md`, `docs/adr/`.
