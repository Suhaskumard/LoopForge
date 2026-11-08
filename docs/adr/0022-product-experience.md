# ADR-0022: A product people can use - accounts, notifications, guidance, browser tests (Phase 15)

**Status:** accepted. **Principle:** account and email flows are security work, not polish; every claim below is
backed by a test that runs in CI.

## What was built

| Piece | What it does |
|---|---|
| Mail backend (`services/mail_service.py`) | `console` (dev, logs), `memory` (tests / e2e outbox), `smtp` (real). Sending never raises into the request. Production refuses anything but `smtp`. |
| Email verification | `users.email_verified_at`; hashed, single-use, expiring tokens in `email_tokens` (`services/email_token_service.py`). `POST /auth/verify-email`, `/auth/resend-verification`. |
| Password reset | `POST /auth/password-reset/request` always answers 202 with the same body and is rate limited per `IP|address`; `/confirm` sets the password, marks the address verified and ends **every** session. |
| SSO linking | A password account is linked to a matching SSO identity only when its address is **verified**; otherwise the old refusal stays. New SSO users are created verified (the IdP verified them). |
| Invitations | `org_invites` (hashed token, role, expiry, revoke). `POST /orgs/{id}/invites` always answers the same (no "no such user" oracle); `POST /invites/accept` needs a signed-in, **verified** account whose address equals the invite. |
| Sessions | `refresh_tokens` gained `user_agent`, `ip`, `last_used_at`; `GET /auth/sessions` (one row per rotation family, current one marked via `X-Refresh-Token`), `DELETE /auth/sessions/{family}`. |
| Notifications | `notifications` table + in-app bell, email (per-user preference) and webhook for the same event: `task.completed/failed/escalated`, `approval.needed`, `quota.near_limit`. De-duplicated by `(user, dedupe_key)`. Best effort: a failure never changes a run. |
| Per-member quotas | `memberships.token_quota_month` / `max_tasks_month`, `tasks.created_by`. A task is limited by the **lower** of the org's and its creator's remainder (`quota_service.token_ceiling`). Warning at `QUOTA_WARN_FRACTION` (0.8), once per month per quota. |
| Guided experience | Task templates (`GET /templates`), onboarding checklist derived from stored facts (`GET /me/onboarding`), failure explanation in the report (what failed / what Repair tried / what a human should do - built only from stored records), approval review comments (`approval_comments`) next to the existing diff view. |
| Browser tests | Playwright against the real API (scripted LLM/sandbox), the real Vite server and an in-process mail outbox: sign-up + verify, template -> task -> completed -> report -> zip, approval gate with a comment, password reset, sessions, invite + org switch + admin gating, per-member limits; axe (WCAG 2 A/AA) with **no serious or critical violations** on every main screen; phone width (Pixel 7) with no sideways scroll. |

## Decisions
- **Same answer, always** for reset requests and invitations. Cost: an admin cannot learn from the reply whether an address
  was already registered; they see pending invitations instead.
- **Tokens are never stored raw** (SHA-256), are single use, and a new token of the same purpose kills older ones.
- **Verification is not required to use the app**, only to accept invitations and to be linked to SSO. A banner nags. This keeps
  onboarding light while the two actions that could cross an account boundary stay gated.
- **Registration still answers 409 for a taken address** (unchanged, `POST /auth/register`). Removing it needs a "check your email"
  sign-up flow that this phase did not build; see Known limits.
- **Member quota attribution is by task creator** (`tasks.created_by`), not by who pressed Start. Tasks created before migration
  0010 have no creator and count only against the organization.
- **Email goes through a pluggable backend, SMTP only.** SES is reachable through its SMTP endpoint; no AWS SDK dependency.
- **The e2e outbox route exists only in `scripts/dev_demo_server.py`** (`E2E=1`), never in the application.

## Known limits
- **Registration is still an enumeration oracle** (409 on a taken address). Login and reset are not.
- **Deliverability is not tested.** SPF/DKIM/DMARC, bounces and provider rate limits are the operator's job; the Mailpit test proves
  the SMTP conversation, not inbox placement.
- Mail is sent synchronously after the response in the web process (FastAPI background task); there is no retry queue. A failed
  send is logged and the user can request another link.
- Notification emails are individual messages, not digests; there is no per-event preference beyond the on/off switch.
- Axe finds a subset of accessibility problems; this is not a manual audit or screen-reader test. Only Chromium is exercised.
- The demo server's scripted story is one fixed story: e2e checks UX and plumbing, not the quality of generated code.
- Inline review comments attach to a file and optional line of an approval; they are not anchored to diff hunks and do not block
  approval.
- Per-member quota warnings go to that member; org quota warnings go to admins. Nobody is warned about *other* members' caps.
