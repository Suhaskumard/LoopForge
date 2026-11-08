# Roadmap: Phases 8-12 (draft)

Status: **proposal, nothing here is built.** Phases 1-7 are in the repo. The README already names the post-MVP
direction ("7 scale, 8 languages/repos, 9 advanced intelligence, 10 enterprise"); this draft follows it and adds
Phases 11-12. Each phase ends with a gate script like `scripts/phaseN_gate.sh` (= previous gate + new checks).

## Rule for every phase
No claim without evidence: every capability ships with tests, and any quality or cost claim comes from
`benchmarks/` runs, never from the synthetic oracle (see `docs/evaluation_report.md`).

---

## Phase 8 - Existing repositories and more languages
**Goal:** work on code that already exists, not only greenfield FastAPI projects.
- **Repository-input mode:** a task takes a git URL/zip/upload as the starting workspace (iteration 0), plus a
  requirement ("fix X", "add Y"). Today bug-fix benchmark tasks embed the broken code in the requirement text
  (ADR-0012); this removes that limitation.
- **Repo understanding agent:** builds a file map, entry points and test commands before planning; the Planner
  receives it. Changes are produced as patches, not whole-project rewrites; the diff view already exists.
- **Language adapters:** a `LanguageProfile` (test command, lint, security tool, sandbox image) per language.
  Start with Python (existing) + JavaScript/TypeScript (Jest/Vitest, ESLint) behind the same Verifier interface.
- **Sandbox:** one image per language; same isolation rules as ADR-0008 (no network, resource caps).
- **Benchmarks:** add a repo-input task category (>= 10 tasks) and JS tasks (>= 10).
- **Gate:** repo-input task fixes a seeded bug end to end offline; adapter contract tests; benchmark validator
  passes for the new tasks.
- **Risks:** untrusted repos (malicious scripts, huge repos) -> size/file-count limits, no host execution, secret
  scanning before anything is sent to the model.

## Phase 9 - Smarter loop (advanced intelligence)
**Goal:** fewer iterations and less cost for the same success rate.
- **Failure classifier:** categorize failures (syntax, import, logic, test-itself-wrong, environment) and route to
  specialized repair strategies.
- **Targeted context:** send the Repair agent only the relevant files/functions plus the failing trace (token
  savings measured by the existing analytics).
- **Test-quality guard:** detect tests the Builder weakened or deleted (extend the existing cheating guard).
- **Model routing:** cheap model for Planner/Documenter, stronger for Repair/Reviewer; configurable per agent.
- **Learning from history:** retrieve similar past failures and the repairs that worked (per organization data).
- **Gate:** ablation (A1-A4 style) on the 30+ benchmark tasks shows the effect with confidence intervals; a
  change that does not help is reported as not helping.

## Phase 10 - Enterprise
**Goal:** safe to run for a team.
- **Organizations and roles:** orgs, members, RBAC (viewer / developer / approver / admin); tasks and reports are
  org-scoped.
- **SSO:** OIDC login (keep email+password as fallback); per-org policies.
- **Audit log:** append-only record of who did/approved what (extends the approval gate, ADR-0013).
- **Quotas and budgets:** per-org/user token and cost caps, enforced server-side like today's per-task budget.
- **Secrets and data handling:** configurable retention, export/delete of an org's data, redaction extended
  (`utils/redact.py`).
- **Gate:** authorization matrix tests (every endpoint x every role), cross-org isolation tests, audit completeness
  test.

## Phase 11 - Integrations and delivery
**Goal:** fit into existing developer workflows.
- **Git provider integration (GitHub first):** open a branch + pull request with the generated/repaired code and
  the final report as the description; approval gate before any push.
- **CI feedback:** optionally use the repo's own CI result as an extra verification signal.
- **Webhooks and API tokens:** task events to Slack/webhook endpoints; scoped API keys for automation; a small
  CLI (`loopforge run --repo ... --requirement ...`).
- **Gate:** integration tests against a mock Git server; no push without recorded approval; webhook signing
  tests.

## Phase 12 - Production operations and real evaluation
**Goal:** run it reliably and publish measured results.
- **Observability:** metrics (loop success, iterations, cost, queue depth, lease takeovers), structured logs with
  request/task ids, tracing across API -> worker -> sandbox, dashboards and alerts.
- **Reliability:** load and chaos tests (worker killed mid-iteration, DB failover), backups/restore drill,
  zero-downtime migrations, autoscaling workers.
- **Security hardening:** third-party pen-test or equivalent review, dependency/image scanning in CI, sandbox
  escape review (extends `docs/security_review.md`).
- **Real evaluation:** run E1-E3 and ablations with a real model and Docker (still "To be measured"), publish
  `docs/evaluation_report.md` with real numbers, cost per solved task, and honest failure analysis.
- **Gate:** all earlier gates + recovery drill + published, reproducible benchmark results.

---

## Suggested order and dependencies
8 -> 9 (needs repo context) -> 10 (needs real multi-user need) -> 11 (needs 8 and 10) -> 12 (continuous; the
real evaluation can start as soon as an API key and Docker are available, and should be done **before** Phase 9
so its improvements are measured against a real baseline).

## Open questions for the owner
1. Is JavaScript/TypeScript the right second language, or Java/Go?
2. Single-tenant self-hosted or multi-tenant SaaS (changes Phase 10 scope a lot)?
3. Which Git provider first (GitHub, GitLab)?
4. Budget for real-model benchmark runs (Phase 12 evaluation, and the Phase 9 baseline)?
