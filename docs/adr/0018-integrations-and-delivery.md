# ADR-0018: Integrations and delivery (Phase 11)

**Status:** accepted (Phase 11). GitHub first; other providers are not implemented.

## Decision

### Pull requests behind an approval
- `publish_requests` (task, org, repo, base/head branch, status `requested|approved|rejected|pushed|failed`,
  requester, decider, PR url, CI state). It is separate from the loop's `approval_requests` on purpose: a COMPLETED
  task has no allowed status transitions, and the loop gate resumes a task through `transition()`.
- Only a COMPLETED task can be published. The change set is the final iteration versus the seed; every file is scanned
  with `scan_secrets` at request time and again at push time, and any finding blocks the publish (422 / failed).
- **`publish_service.push` is the only code that writes to the provider.** It re-reads the row under a lock and refuses
  unless `status == approved` and `decided_by` is set (same pattern as ADR-0013). An approved row is pushed once.
- The requester cannot approve their own request unless the organization has a single member. Requested, approved,
  rejected, pushed and failed are all recorded in `audit_log`.
- GitHub is driven over its REST Git Data API (tree -> commit -> ref -> pull request) with `httpx`; no git binary,
  working copy or SSH key is involved. The PR body is the final report (`report_service.render_markdown`). The org's
  GitHub token is stored Fernet-encrypted (key from `SECRETS_KEY`, else derived from `JWT_SECRET`) and never returned.

### CI feedback
After the PR is open, `GET /tasks/{id}/publish` reads the head commit's check runs and stores `pending|success|failure|none`.
It is **informational**: it never changes the task's verdict.

### API tokens
`lfk_...` tokens, shown once, stored as SHA-256. A token is bound to one organization and has a scope (`viewer`,
`developer` or `approver`, never `admin`); its effective role is `min(owner's current role, scope)`, so removing the
owner or lowering their role takes effect at once. Because admin routes need `admin`, a token cannot create tokens,
webhooks or integrations. Calls made with a token record the token id in the audit entry. Tokens can be revoked and expire.

### Webhooks
Per-organization endpoints receive `task.completed|failed|escalated`, `publish.*` and `ping`. The body is signed:
`X-LoopForge-Signature: t=<unix>,v1=hex(HMAC-SHA256(secret, "<t>.<body>"))`; `webhook_service.verify_signature`
compares in constant time and rejects timestamps outside a 5-minute window. Targets must be `https`, carry no
credentials and resolve only to public addresses (checked at creation and again on every attempt); redirects are not
followed. Failed deliveries retry with exponential backoff up to `WEBHOOK_MAX_ATTEMPTS`; the worker delivers them
(inline mode delivers right after the task finishes). Payload strings are secret-redacted. A `slack` format sends `{"text": ...}`.

### CLI
`python -m app.cli run --repo URL --requirement TEXT [--wait]` and `publish TASK --repo owner/name`, using
`LOOPFORGE_TOKEN` / `LOOPFORGE_URL`. Exit code 0 only when the task COMPLETED.

## New dependency
None (`cryptography` was already pinned in `requirements.txt`).

## Verified by
`test_phase11_publish.py` (mock GitHub records every request: none before approval, none after rejection, none twice),
`test_phase11_tokens.py`, `test_phase11_webhooks.py`, `test_phase11_cli.py`, the route-completeness matrix in
`test_phase10_authz.py`, and the migration parity test.

## Known limits (honest list)
- Not tested against live GitHub or a real webhook receiver; the "Git server" is an `httpx.MockTransport`.
- Slack support is the incoming-webhook payload shape only; no Slack app, no GitLab/Bitbucket.
- The PR is a single commit authored by the token's owner; it cannot update an existing PR or resolve conflicts.
- A "failed" publish is final: request a new one. CI state is polled on read, not pushed to us.
- WebSocket streaming does not accept API tokens. `GET /orgs` still lists all of the token owner's organizations.
- The DNS check for webhook targets is not pinned to the connection (a rebinding race remains possible).
- Token and webhook-secret storage: webhook secrets are stored in plain text (needed to sign); protect the database.
