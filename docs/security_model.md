# LoopForge — Security Model

| Threat | Control | Where / proof |
|---|---|---|
| Credential stuffing / brute force | Failed logins logged in `login_attempts` (DB-backed, shared across workers); 5 failures per (IP,email) per 5 min → 429 + `Retry-After`; success clears the counter | `services/auth_service.py`, `test_auth_sessions.py`, `test_hardening.py` |
| Weak passwords | ≥8 chars, letter + digit; bcrypt hashing | `schemas/user.py`, `utils/security.py` |
| Stolen access token | 15-min lifetime; `tv` claim must equal `users.token_version` → `logout-all` kills all live access tokens instantly | `api/dependencies.py` |
| Stolen refresh token | Opaque 384-bit random; only SHA-256 stored; **rotation on every use**; replay of a spent token revokes the whole family | `services/auth_service.rotate`, `test_refresh_token_reuse_revokes_whole_family` |
| Forged / expired JWT | HS256 signature + `exp` verified; unknown subject rejected | `test_expired_and_foreign_tokens_rejected` |
| Weak production secret | App refuses to start with `JWT_SECRET` = default or <32 chars when `ENVIRONMENT=production` | `config.py` |
| Cross-tenant data access | Phase 10: all queries scoped by **organization** (`Project.org_id`); foreign IDs return **404**; a non-member of the header org gets 403; every route x role is tested and the matrix is checked complete against `app.routes` | `test_phase10_authz.py` |
| Privilege escalation inside an org | Roles read from the DB per request (no role in the JWT); approve/reject need *approver*; admin actions need *admin*; the last admin cannot be removed | `test_phase10_authz.py` |
| Tampering with the audit trail | `audit_log` UPDATE/DELETE rejected by DB triggers; secrets redacted on write | `test_phase10_governance.py` |
| SSO token forgery / replay | PKCE + state + nonce, JWKS-verified asymmetric signature only, `iss`/`aud`/`exp` checked, one-time provider codes; no automatic linking to password accounts | `test_phase10_oidc.py` |
| Quota abuse / runaway spend | Server-side monthly token and task quotas; runs capped at what is left | `test_phase10_governance.py` |
| Lost updates / races | `version_id_col`, `If-Match`/ETag, row lock on status transitions | `test_concurrency.py` |
| Invalid state in DB | CHECK constraints (status values, iterations ≥1), UNIQUE (task, iteration#), UNIQUE (task, req_id) | `models.py`, `test_hardening.py` |
| Info leaks via errors | Unhandled exceptions return a generic 500 + request id; details only in server logs | `api/errors.py` |
| Clickjacking / sniffing / caching | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` | `middleware.py` |
| Prompt injection (requirement text, repo files, model output) | Untrusted text fenced in `<untrusted_input>` with spoofed delimiters neutralised; fixed security policy leads every system prompt; model output is data, validated by strict schemas — it can never cause an action | `agents/base.py`, `test_agents.py::test_injection*` |
| Path traversal / workspace escape by generated code | Schema rejects `..`, absolute, drive, UNC, backslash, hidden files, odd extensions; workspace re-resolves paths, refuses symlinks/junctions, validates **all** paths before writing **any**; Builder emits file changes only (no shell) | `schemas/plan.py`, `services/workspace.py`, `test_workspace.py`, `test_phase2_flow.py::test_file_endpoint_*` |
| Malformed / hostile model output | Strict Pydantic (`extra=forbid`), logged as `agent_output_rejected`, one bounded corrective retry, then FAIL; nothing partially persisted | `test_two_malformed_outputs_fail_and_persist_nothing` |
| Runaway cost | Backend-enforced token budget after every call → ESCALATED; transport retries capped with capped backoff | `utils/token_tracker.py`, `test_token_budget_*` |
| Unsafe dependencies in plans | Dependency specifiers must be `name[==version]`; URLs/VCS/shell metacharacters rejected | `ProjectPlan._deps` |
| Generated code running on the API host | It never does: execution goes through the `Sandbox` interface; `SANDBOX_BACKEND=fake` is refused in production | `execution/sandbox.py`, `config.py` |
| Sandbox escape / resource abuse (§13.1, Addendum §19.1) | Per container: non-root UID 10001, `--read-only` root + noexec `/tmp` tmpfs, `--network none`, `--cap-drop ALL`, `no-new-privileges`, default seccomp, memory/CPU/PID/nofile limits, source mounted read-only, separate `/out` for reports, no Docker socket or host mounts, wall-clock timeout with `docker kill`, `docker rm -f` in `finally` | `build_run_args`, `test_sandbox_controls.py`, `test_docker_real.py` |
| Arbitrary commands in the sandbox | Command allowlist (pytest / ruff only); flags, `-p` plugins and paths validated; no shell | `execution/runner.py` |
| Uncontrolled package installation (Addendum §19.2) | No network and no pip in the image; dependencies baked from `sandbox/approved_packages.txt`; `requirements.txt` must be approved and pinned to that version or the run is blocked and recorded | `execution/dependencies.py`, `test_verifier.py` |
| Fabricated test evidence | Verifier has no LLM; results come only from parsed pytest output; a missing report or timeout is recorded as a failure | `agents/verifier.py`, `evaluation/test_runner.py` |
| Repair writes outside the workspace / weakens the suite | Repair paths pass the same schema + `resolve_safe` checks as the Builder, `modify` needs an existing file, `requirements.txt` edits must satisfy the dependency policy, rejected output is never written; the Decision Engine escalates if the test count ever drops below its best, so tests cannot be deleted to go green | `agents/repair.py`, `orchestrator/decision.py`, `test_repair_reviewer.py`, `test_decision.py` |
| An agent certifying its own work | Repair only produces a new iteration; the graph always re-runs the full suite on it; only the deterministic Decision Engine can accept. The Reviewer cannot override scanner findings or mark criteria met while tests fail | `orchestrator/graph.py`, `agents/reviewer.py` |
| Silent security-scan failure | A Bandit run that times out or returns unreadable output counts as an unapproved high-severity finding, blocking acceptance | `evaluation/quality.py`, `agents/reviewer.py` |
| Endless loops / runaway cost | Iteration, token and wall-clock limits plus repeated-failure fingerprinting all escalate (100% branch-covered) | `orchestrator/decision.py` |
| Container compromise blast radius | Multi-stage image, non-root UID 10001, HEALTHCHECK | `backend/Dockerfile` |

## Phase 5 additions (dashboard)
| Threat | Control | Where / proof |
|---|---|---|
| WebSocket hijack / foreign task streams | JWT (`token` query) verified like REST incl. `tv`; foreign and unknown tasks both close 4404; per-user connection cap (4429) | `api/ws.py`, `test_phase5_ws.py` |
| Cross-origin API use | CORS allow-list from `CORS_ORIGINS` (no wildcard), explicit methods/headers | `main.py`, `test_cors_allows_only_the_configured_origin` |
| XSS via generated code / model output | Rendered strictly as text; `dangerouslySetInnerHTML` is a lint error; nginx CSP; tested with a script-bearing diff | `frontend/src/__tests__/ui.test.tsx`, `nginx.conf` |
| Token theft in the browser | Access token in memory only; refresh token in sessionStorage, rotating, replay revokes the family; single-flight refresh | ADR-0011, `client.test.ts` |
| Analytics leaking across tenants | Every aggregate is joined through `projects.user_id`; foreign ids 404 | `test_analytics_are_owner_scoped` |

## Phase 6
Secret redaction, approval gates, budgets and the expanded injection suite are described and evidenced in `docs/security_review.md` (threat table, tests, residual risks).

## Phase 12 (operations)
`/metrics` is off by default and token-protected when configured; it exports no ids (route templates only). The worker
metrics port is unauthenticated: restrict it by network policy. Migrations run once per release under a PostgreSQL
advisory lock; the production image contains runtime dependencies only. Backups are verified by checksum before a
restore and refuse path-escaping archives, but are **not encrypted** by the scripts. Details, the dependency and
static-analysis results, and the sandbox flag review: `docs/security_review.md` (Phase 12 additions), ADR-0019.

Phase 13 ran these controls on real infrastructure (PostgreSQL 16, the real Docker sandbox, Keycloak) and found and fixed two
real defects: short production JWT secrets were accepted, and `TRUNCATE` could wipe the audit log on PostgreSQL. See the
"Phase 13 additions" table in `docs/security_review.md` and ADR-0020.

## Known limits (honest list)
- Rate-limit key uses the direct peer address unless `TRUSTED_PROXY_COUNT=N` is set; then the Nth `X-Forwarded-For` entry from the right is used and anything further left (client-forged) is ignored (Phase 7, `utils/client_ip.py`).
- LoopForge's own tokens are HS256 with a shared secret (key rotation not built). SSO ID tokens are verified with the provider's asymmetric keys.
- Phase 10 limits (no invitation emails, no SCIM/group mapping, triggers are tamper-resistant not tamper-proof, Postgres paths untested here): ADR-0017.
- No email verification or password reset yet.
- Phase 3 executes generated code only inside the sandbox. Ordinary Docker containers are **not** an absolute security boundary against hostile code; evaluate gVisor/Firecracker and rootless Docker for stronger isolation (spec §13.1). No custom seccomp/AppArmor profile ships yet (Docker defaults apply). Dependency vulnerability scanning and hash-verified retrieval (Addendum §19.2 items 4-6) are not implemented; the approved-package list is the only control.
- WebSocket tokens travel in the URL query: keep access logs from recording query strings; tokens expire in 15 minutes.
- Prompt-injection defences reduce, but do not eliminate, the chance a real model is misled; the hard guarantees are the schema/workspace refusals and the absence of any shell or network capability in agents.
- Cancel is cooperative: the loop checks before each step, so an in-flight sandbox run finishes (bounded by its timeout) before the task stops.
- A task run is guarded across processes by a lease with a heartbeat (ADR-0014): a second process cannot drive a live run, and a dead owner's run is taken over after the lease expires and resumes from its checkpoint (proved by `scripts/chaos_drill.py`).
- Repair/Reviewer prompts reduce but cannot eliminate model misjudgement; the hard guarantees are the deterministic checks above.
