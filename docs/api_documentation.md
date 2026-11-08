# API (Phase 1) — base path `/api/v1`

Interactive docs: `GET /docs` (Swagger) · `GET /openapi.json`.

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /auth/register | – | 201; 409 duplicate email; 422 weak password |
| POST | /auth/login | – | form `username`,`password` → `{access_token, refresh_token, expires_in}`; 401; 429 after 5 failures |
| POST | /auth/refresh | – | `{refresh_token}` → new pair (old one invalidated); 401 on reuse/expiry |
| POST | /auth/logout | – | `{refresh_token}` → 204, revokes that session family |
| POST | /auth/logout-all | Bearer | 204; invalidates every access + refresh token |
| GET | /auth/me | Bearer | current user |
| POST/GET | /projects | Bearer | `GET ?limit=1..200&offset=` |
| GET/PUT/DELETE | /projects/{id} | Bearer | `GET`/`PUT` return `ETag`; `PUT` honours `If-Match` (412) |
| POST/GET | /tasks | Bearer | `POST {project_id, requirement, max_iterations?, acceptance_criteria?, token_budget? (>=1000, <= server cap), max_cost? (estimated USD), require_plan_approval?}` |
| GET | /tasks/{id} | Bearer | returns `ETag` |
| POST | /tasks/{id}/source | Bearer | Phase 8: multipart `file` (zip) for a task created with `source_type: "zip"`; only while PENDING; 422 on an unsafe/oversized/empty/mismatched-language repo, 409 otherwise. `POST /tasks` also takes `source_type` (`none`/`zip`/`git`) and `git_url` (plain https, no credentials); `/start` is 409 for a zip task until the upload succeeded |
| POST | /tasks/{id}/status | Bearer | Phase-1 stand-in; invalid transition → 409; `If-Match` supported |
| GET | /tasks/{id}/events | Bearer | audit trail |
| POST | /tasks/{id}/start | Bearer | **202**; PENDING → PLANNING, then the loop (plan → build → test → review → decide → repair …) runs in the background until COMPLETED / ESCALATED / CANCELLED / FAILED. 409 unless PENDING; 412 on stale `If-Match`; 503 if the LLM provider is not configured |
| GET | /tasks/{id}/plan | Bearer | validated plan of the latest iteration (404 until planned) |
| GET | /tasks/{id}/requirements | Bearer | `REQ-###` records: type, priority, `impl_mapping`, verification status |
| GET | /tasks/{id}/agent-runs | Bearer | chronological runs: agent, status (`success|failed|timeout`), tokens, duration, error |
| GET | /tasks/{id}/files | Bearer | generated files (path, sha256) of the latest iteration |
| GET | /tasks/{id}/files/{path} | Bearer | file content; only files recorded as artifacts; confined to the workspace |
| POST | /tasks/{id}/cancel | Bearer | Stop a non-terminal task (→ CANCELLED); the loop notices before its next step. 409 if already finished |
| POST | /tasks/{id}/retry | Bearer | FAILED/ESCALATED → PENDING; call `/start` afterwards for a fresh run with a new iteration budget (history is kept) |
| POST | /tasks/{id}/resume | Bearer | **202**; continue an interrupted run from its checkpoint. 409 if nothing is resumable |
| GET | /tasks/{id}/iterations | Bearer | versions v1..vN: status, tests, quality score, Decision Engine verdict, repair summary |
| GET | /iterations/{id} | Bearer | one iteration: test results (with coverage), agent runs, review, Ruff/Bandit report, file hashes |
| GET | /iterations/{id}/diff | Bearer | unified diffs against the previous iteration (all files for the first) |
| GET | /iterations/{id}/logs | Bearer | execution logs of the iteration |
| GET | /tasks/{id}/iterations/{n}/test-results | Bearer | `test_results` rows: totals, `details.failures[]` (nodeid, message, traceback), `timed_out` |
| GET | /tasks/{id}/iterations/{n}/logs | Bearer | execution stdout/stderr stored as `log` artifacts, with sha256 |
| GET | /iterations/{id}/diff?against={iteration_id} | Bearer | compare with **any** iteration of the same task (default: the previous one); other task's id → 404 |
| GET | /iterations/{id}/files/{path} | Bearer | file content as it was in that iteration |
| GET | /tasks/{id}/download | Bearer | zip of the latest iteration's recorded source files |
| GET | /analytics/overview | Bearer | KPIs (spec §9.1): success rate, avg iterations, test pass rate, avg quality, avg time, avg cost (estimate), failure distribution, repair outcomes. `null` = not computable |
| GET | /analytics/tasks/{id} | Bearer | per-iteration tests, quality trend, tokens, estimated cost, execution time |
| GET | /analytics/iterations/{id} | Bearer | one iteration: tests, per-agent tokens/time, decision |
| GET | /analytics/agents | Bearer | per-agent runs, success rate, average duration, tokens |
| GET | /agents/{name}/status | Bearer | last run and counters for one agent |
| WS | /ws/tasks/{id}?token=<access JWT> | token | live events: `task_started agent_started agent_completed sandbox_started tests_completed iteration_completed retry_scheduled escalated task_completed task_cancelled` (+ `task_failed`). History is replayed on connect; closes after the terminal event. Close codes: 4401 bad token, 4404 unknown/foreign task, 4429 too many sockets |
| GET | /tasks/{id}/report | Bearer | final report built from stored records: outcome, escalation reason, iteration history, traceability (requirement -> files -> tests -> status), acceptance criteria, tests, quality, tokens/estimated cost, approvals |
| GET | /tasks/{id}/report.md | Bearer | the same as Markdown (+ the generated project README when the Documentation Agent wrote one) |
| GET | /tasks/{id}/approvals | Bearer | approval requests (`plan`, `large_repair`) with status |
| POST | /tasks/{id}/approvals/{aid}/approve | Bearer | release a paused run (resumes from its checkpoint). 409 if not pending |
| POST | /tasks/{id}/approvals/{aid}/reject | Bearer | reject -> task ESCALATED. 409 if not pending |
| GET | /agents | Bearer | the six agents, which are implemented, and what each may not do |
| GET | /health · /health/ready | – | liveness · DB readiness (503 if down) |

Errors: `{"error":{"code","message","request_id","details?"}}`. Codes: `bad_request unauthorized forbidden not_found conflict precondition_failed validation_error rate_limited unavailable internal_error`. Every response carries `X-Request-ID`.

Example:
```bash
curl -X POST :8000/api/v1/auth/register -H 'content-type: application/json' -d '{"email":"a@b.co","password":"password123"}'
curl -X POST :8000/api/v1/auth/login -d 'username=a@b.co&password=password123'
```

## Phase 10 - organizations (all under `/api/v1`)

Work endpoints take the organization from the `X-Org-Id` header (default: your first organization); a non-member gets 403. Routes with `{org_id}` in the path return 404 to non-members. Roles: viewer < developer < approver < admin. Every `GET` above needs **viewer**; create/start/cancel/retry/resume/upload/PUT/DELETE of projects and tasks need **developer**; approve/reject need **approver**.

| Method | Path | Role | Notes |
|---|---|---|---|
| GET / POST | /orgs | any user | my organizations with my role / create one (creator = admin) |
| GET | /orgs/{org_id} | viewer | settings |
| PATCH | /orgs/{org_id} | admin | `name`, `token_quota_month`, `max_tasks_month`, `retention_days`, `redact_pii`; send `null` to clear a cap |
| GET | /orgs/{org_id}/usage | viewer | tokens and tasks this month vs. quota |
| GET / POST | /orgs/{org_id}/members | viewer / admin | `POST {email, role}`: the user must already be registered; 409 duplicate |
| PATCH / DELETE | /orgs/{org_id}/members/{user_id} | admin | 409 if it would leave no admin |
| GET | /orgs/{org_id}/audit | admin | `?action=&actor_id=&limit=&offset=`, newest first |
| GET | /orgs/{org_id}/export | admin | zip of JSON (no secrets) |
| POST | /orgs/{org_id}/retention/run | admin | purge finished tasks older than `retention_days` |
| DELETE | /orgs/{org_id}/data | admin | body `{confirm: <slug>}`; removes all projects and tasks, keeps org/members/audit |
| GET | /auth/config | - | `{sso_enabled}` |
| GET | /auth/sso/login | - | 302 to the identity provider (sets the signed state cookie) |
| GET | /auth/sso/callback | - | 302 to the SPA with `#access_token=&refresh_token=` or `#error=` |
| WS | /ws/tasks/{id}?token=&org= | viewer | `org` optional (default: first membership) |

429 is returned when an organization quota is reached (`quota.blocked` is audit-logged). Approvals now record who decided (`approval_requests.decided_by`).

## Phase 11 - integrations and delivery (all under `/api/v1`)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/tasks/{id}/publish` | developer | body `{repo: "owner/name", base_branch}`; COMPLETED tasks only; 422 if secrets are found |
| GET | `/tasks/{id}/publish` | viewer | requests for the task; refreshes CI state |
| POST | `/publish/{id}/approve` | approver | records the decision, then pushes; requester cannot self-approve |
| POST | `/publish/{id}/reject` | approver | nothing is ever pushed |
| PUT | `/orgs/{org_id}/integrations/github` | admin | `{token}` stored encrypted |
| GET/POST | `/orgs/{org_id}/tokens` | admin | create returns the `lfk_` secret once |
| DELETE | `/orgs/{org_id}/tokens/{id}` | admin | revoke |
| GET/POST | `/orgs/{org_id}/webhooks` | admin | create returns the signing secret once |
| DELETE | `/orgs/{org_id}/webhooks/{id}` | admin | disables |
| POST | `/orgs/{org_id}/webhooks/{id}/test` | admin | sends a signed `ping` |
| GET | `/orgs/{org_id}/webhooks/{id}/deliveries` | admin | last 50 deliveries |

Authenticate with `Authorization: Bearer lfk_...`; a token is bound to its organization and capped at its scope. Webhook signature: `X-LoopForge-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`.
