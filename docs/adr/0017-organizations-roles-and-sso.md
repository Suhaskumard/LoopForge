# ADR-0017: Organizations, roles, audit log, quotas and OIDC SSO (Phase 10)

**Status:** accepted (Phase 10). **Scope decisions (owner):** multi-tenant organizations; generic OIDC with the
password login kept as a fallback.

## Decision

### Tenancy
- `organizations`, `memberships(org, user, role)`; `projects.org_id` is NOT NULL. A task belongs to an organization
  through its project, so **every** read and write is scoped by `Project.org_id` (the old `Project.user_id` stays as
  "created by"). A user may belong to several organizations; registering creates a personal organization.
- Active organization: `X-Org-Id` header (REST) or `?org=` (WebSocket), validated against the caller's memberships;
  absent = the user's first membership. **Roles are read from the database on every request**, never from the JWT, so
  a role change or removal applies to the very next request.
- Roles `viewer < developer < approver < admin`: read; create/start/cancel/retry/resume/upload; approve or reject
  an approval gate (also recorded as `approval_requests.decided_by`); administer (members, limits, audit log, export,
  retention, deletion). Non-members of an organization named in a **path** get 404 (no existence leak); non-members
  using the header get 403.
- Cross-tenant leak closed in Phase 9 code: similar-repair retrieval is per organization.
- Migration `0006` moves each existing user and their projects into a personal organization (user = admin).

### Audit log
`audit_log(org_id, actor_id, action, target, detail, ip, created_at)` is written only through
`services/audit_service.record`, redacts secrets (and email/phone when the organization turned `redact_pii` on), and is
**append-only enforced by database triggers** that reject UPDATE and DELETE (SQLite + PostgreSQL; installed both by
migration 0006 and whenever `create_all` builds the table). The per-task `audit_events` (loop telemetry) are unchanged.
Recorded: register/login/SSO login, project and task create/start/cancel/retry/resume, approval decisions, member
add/role change/remove, organization setting changes, quota refusals, export, retention runs, data deletion.

### Quotas
Organization `token_quota_month` and `max_tasks_month` (NULL = no cap), counted per UTC calendar month from
`agent_runs.tokens_used` and `tasks.created_at`. Enforced when a task is created (task count) and when a run starts
(tokens), and the run is capped in flight at what is left (`quota_service.token_ceiling` -> the tracker and the
Decision Engine limit), so a task escalates instead of overspending. These are token estimates, not billing data.

### Data lifecycle
`retention_days` (finished tasks only; running tasks are never purged), an admin export (zip of JSON: organization,
members, projects, tasks, reports - no password hashes, tokens or source files), and a delete-all-data action that
needs the organization slug typed as confirmation and is audit-logged **before** it runs. The organization, members
and audit log survive deletion.

### OIDC
Authorization code + PKCE (S256) + `state` + `nonce`; state, nonce and verifier ride in a short-lived, HttpOnly,
signed cookie (no server-side state). Provider metadata via discovery (issuer must match). The ID token is verified
with a key chosen by `kid` from the provider's JWKS; only asymmetric algorithms are accepted (so an
HS256/"public key as secret" confusion fails); `iss`, `aud`, `exp`, `iat`, `sub`, `nonce` and `email_verified` are
required. Optional `OIDC_ALLOWED_DOMAINS`. A successful login issues the normal LoopForge access/refresh pair, handed
to the SPA in the URL **fragment** (never sent to a server). Disabled unless `OIDC_ISSUER` is set; production requires
https and a client secret.

**Account linking is conservative.** An existing *password* account with the same email is **not** linked
automatically: LoopForge does not verify registration emails, so auto-linking would let someone who pre-registered a
victim's address take over their SSO login. The user is told to sign in with the password.

## New dependency
`cryptography==46.0.7` (needed by PyJWT to verify RS256/ES256). Pinned in `backend/requirements.txt`.

## Verified by
`test_phase10_authz.py` (every route x every role; the matrix is checked for completeness against `app.routes`; cross-org
isolation incl. WebSocket; role changes apply immediately; last admin protected), `test_phase10_governance.py`
(audit completeness, append-only, redaction, quotas, retention, export, deletion), `test_phase10_oidc.py` (fake
provider: valid login and 10 kinds of bad tokens, state/cookie attacks, code replay, no takeover),
`test_phase10_migration.py` (0006 on real data, triggers, downgrade) and `frontend/src/__tests__/orgs.test.tsx`.

## Known limits (honest list)
- No invitation emails: an admin adds an **already registered** user by email.
- No SSO group/role mapping, no SCIM, no automatic domain -> organization mapping; SSO users start in a personal org.
- No per-member quotas (organization level only); quotas are not billing.
- LangGraph checkpoint files and any backups outside the app are not covered by retention/deletion.
- The audit log is tamper-**resistant** (DB triggers), not tamper-proof: someone with database superuser rights can drop
  the triggers. Ship it to external storage if that matters.
- Login-failure and token-refresh events are not in the audit log (rate-limit table already records failures).
- Postgres-specific parts (trigger function, migration) are written for it but were exercised only on SQLite here; run the
  suite with `TEST_DATABASE_URL` to cover them.
