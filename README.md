# LoopForge

Autonomous, feedback-driven AI software-engineering platform: natural-language requirement → plan → generated Python → sandboxed tests → independent review → deterministic retry/accept/escalate, until measurable acceptance criteria are met.

**Status:** Phases 1–12 built (foundation, agents, sandbox, feedback loop, dashboard + analytics, hardening + evaluation harness, scale-out worker, existing repositories + JavaScript, smarter repair loop, organizations/roles/SSO/audit, integrations, operations). **No benchmark result has been measured yet** (needs an API key): see `docs/evaluation_report.md`. Roadmap: spec phases 1–6, then post-MVP phases 7–10 (scale, languages/repos, advanced intelligence, enterprise); 11–12 (integrations, production ops + real evaluation) are drafted in `docs/roadmap_phases_8_12.md`.

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

## Phase 12 - production operations and the real-evaluation kit
- **Observability:** JSON logs carry `request_id` (and `job_id`/`task_id` while work is processed); the API request id follows the job to the worker. `GET /metrics` (`METRICS_ENABLED`, optional `METRICS_TOKEN`) and a worker metrics port expose Prometheus series; alert rules, a Grafana dashboard and a KEDA example are in `deploy/observability/`. Operator guide: `docs/operations.md`.
- **Reliability:** pooled DB connections are pinged and recycled; migrations run once per release (`migrate` service, PostgreSQL advisory lock); the image ships runtime dependencies only. Drills you can run: `python scripts/chaos_drill.py` (kills a real worker mid-task; another finishes it), `python scripts/backup_drill.py`, `python scripts/load_test.py`; `scripts/backup.sh`/`restore.sh` for PostgreSQL (not run here).
- **Security:** bandit (medium+ fails), `scripts/security_scan.sh`, CI jobs for pip-audit/npm audit/SBOM/Trivy (CI only). A real scan found HIGH advisories in `react-router-dom`; fixed.
- **Real evaluation:** `make eval` runs `benchmarks/preflight.py` (lists every blocker, spends nothing) then E1-E3; manifests record the git commit and hashes. **No results exist yet: still "To be measured".** ADR-0019, `make gate12`.

## Phase 11 - integrations and delivery
- **GitHub pull requests behind an approval**: a developer requests a publish for a COMPLETED task (`POST /tasks/{id}/publish`), an approver (not the requester) approves, and only then is a branch + PR opened with the final report as the description. Change set is scanned for secrets; every step is in `audit_log`. CI check results are shown as an informational signal.
- **API tokens** (`lfk_...`, per organization, scope viewer/developer/approver, revocable, expiring) and **signed webhooks** (`X-LoopForge-Signature`, HMAC-SHA256 with timestamp, retries, SSRF guard, Slack format).
- **CLI**: `LOOPFORGE_TOKEN=lfk_... python -m app.cli run --repo https://github.com/o/r --requirement "..." --wait`.
- Tested against a mock Git server only; no live GitHub run. Migration `0007`. ADR-0018. `make gate11`.

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

## Phase 7 - scale-out
- `RUN_MODE=queue` makes the API enqueue `jobs` rows instead of running the loop in-process; `python -m app.worker` (any number of them, `docker compose --profile workers up`) claims and runs them. Default `inline` is unchanged.
- `services/lease_service.py`: per-task `run_leases` row with heartbeat (`LEASE_TTL_SECONDS`); a second process cannot drive a task a live process holds, and a dead owner's task is taken over after expiry. `job_service.recover` re-queues resumes for orphaned work.
- `TRUSTED_PROXY_COUNT` for correct login rate-limit keys behind proxies. Details and limits: ADR-0014.
- `make gate7` = Phase 6 gate + the Phase 7 tests.

## Phase 2 configuration
`LLM_PROVIDER=openai|fake`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `WORKSPACE_ROOT`, `LLM_MAX_RETRIES`, `LLM_TIMEOUT_SECONDS`, `MAX_TOKEN_BUDGET`. With `LLM_PROVIDER=fake` the built-in employee-management demo is served (rejected in production). Live smoke test: `cd backend && pytest -m live` (needs a key).
