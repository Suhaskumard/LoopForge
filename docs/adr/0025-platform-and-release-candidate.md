# ADR-0025: Platform surface and a release candidate (Phase 18, core scope)

**Status:** accepted. Built and tested here: a versioned public API contract, per-token rate limits, idempotency keys, uniform pagination, usage reports and plans,
Python and TypeScript SDKs, a packaged CLI with completions, an upgrade test, release documents and a docs site with a link check.
**The version is `1.0.0-rc1`, not `1.0.0`**, on purpose (see "Why not 1.0.0").

## Scope chosen
The roadmap's Phase 18 is much larger. The owner chose the **core platform** and a **release candidate only**. Built: items above. **Deferred, not built:** GitHub App and PR-comment
commands, GitLab, Slack/Teams bot, IDE extension, pluggable agents/tools, shared benchmark-task packs, Helm chart / Terraform reference deployment, hosted docs site, publishing the SDKs.

## Decisions
- **One version, one contract.** `app/version.py` is the only definition; a test compares it with the SDKs, the changelog and the OpenAPI document. `docs/openapi.json` is committed and a
  test fails when the running API differs, so an API change is always a reviewed diff. `openapi_compat.py` flags mechanical breaking changes against `docs/openapi.baseline.json`
  (the Phase 17 surface). It is a tripwire for obvious breakage, not a proof of compatibility.
- **Rate limits and idempotency live in the database**, not a cache, so every API process agrees and nothing new has to be deployed. Fixed one-minute windows (burst up to 2x at a boundary is accepted). Idempotency is
  a middleware over four routes, not four copies; failed attempts are forgotten so a retry really runs; a key is private to the credential and organization.
- **Pagination keeps the plain-array body** and puts paging facts in headers (`X-Total-Count`, `Link`), so no client breaks. A test enumerates the OpenAPI document and demands every array-returning
  `GET` either pages or is listed as bounded with a reason.
- **Plans are limits, not billing.** `Organization.plan` selects defaults from `PLANS_JSON`; an organization's own cap wins; only the platform operator (`loopforge ops set-plan`, database access) assigns a plan, because an
  organization that could assign its own plan would not be limited by it. Usage cost is an estimate from stored token counts, never invoice data.
- **SDKs are thin and tested against the real server**, one contract table (`OPERATIONS`) per language, checked against the OpenAPI document and against each other. Not published.
- **The CLI is the client by default.** `pip install ./backend` needs only `httpx`; database-side commands (`keys`, `ops`) require the `server` extra and say so.
- **Upgrade safety is tested, not asserted.** `scripts/upgrade_test.py` seeds data under the previous schema (SQLite and PostgreSQL), upgrades, and checks old passwords, old tokens, old ciphertext and the audit triggers. It found a
  real hazard while the guide was written: Phase 17's rule that `SECRETS_KEY` differ from `JWT_SECRET` would have orphaned tokens encrypted with the old fallback; `LEGACY_SECRETS_KEY` is the fix.

## Why not 1.0.0
Missing, and named in `docs/releasing.md`: real-model evaluation results (Phase 14's run has not happened), any CI history on GitHub (no workflow has ever run), a verified signed release,
an external penetration test, and an external user. A 1.0 label promises stability the project has not earned yet; the rc lets the surface be tried.

## Known limits
- The rate limiter and idempotency store are single-database; under very high request rates they add a write per request. Not load-tested beyond the Phase 17 profile.
- The breaking-change detector follows local `$ref`s and request shapes only; response-body compatibility is by review.
- SDKs are exercised only against this repository's server. TypeScript tests need Node >= 22.6 (they run TypeScript directly); the type-check uses the frontend's pinned `tsc`.
- The docs site is static HTML for local viewing; external links are not checked; nothing is hosted.
- `markdown` is a development dependency only.
- Upgrade testing covers one earlier schema (`0011`) with synthetic data, not every historical version or your data.
