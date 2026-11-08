# Roadmap: Phases 13-18 (draft, "next level")

Status: **Phase 13 is built (ADR-0020); 14-18 are proposals.** Phase 13 delivered the PostgreSQL, real-sandbox, Keycloak and containerised-worker proofs and the security fixes they found; per-member quotas moved to Phase 15. The rest of this file is unchanged. Starting point (honest): Phases 1-12 are built. Phases 1-11 are committed;
Phase 12 (operations, drills, evaluation kit) is written and tested piece by piece but **uncommitted, and its full gate
never finished**. **No real-model result exists**: every benchmark number so far comes from the synthetic oracle. Large
parts are verified only against fakes (PostgreSQL, real Docker sandbox, a real identity provider, live GitHub, the CI
scanners).

## Principles for this stretch
1. **Prove before adding.** Phases 13-14 add almost no features; they turn "written" into "run and green" and answer the
   research question with a real model. Phases 15-18 are shaped by what 14 finds.
2. **Never publish a number you did not measure.** A negative result is a result. A feature that does not help is removed or
   labelled, not defended.
3. **Every phase ends with a gate script** (= previous gate + new checks) and states what it does *not* cover.
4. **Keep what exists:** deterministic Decision Engine, append-only audit, org/role model, per-switch ablations (E/A/P),
   `make gate*`, ADR-per-phase, "To be measured" discipline.

## Dependencies
```
13 Prove it ──> 14 Measure it ──> 16 Smarter loop (guided by 14)
      │                │
      └──> 15 Real-user product      17 Trust & scale (needs 13; deeper after 14)
                                           └──> 18 Platform & v1.0 (needs 14, 15, 17)
```
13 first, then 14; 15 can run in parallel with 14 (different people / files).

---

## Phase 13 - Prove it (green, committed, run on real infrastructure)
**Goal:** everything already written actually runs, in CI and on PostgreSQL/Docker, from a clean checkout.
- **Repository hygiene:** run the Phase 12 gate to completion; commit Phases 12-13 in reviewable chunks; push; get GitHub
  Actions green (backend, frontend, supply-chain). Fix what CI finds that the local run could not.
- **PostgreSQL for real:** `scripts/test_postgres.sh` (throwaway container) runs the whole suite on PostgreSQL, plus a pytest that
  runs the real Alembic upgrade/downgrade on Postgres (migration 0006 trigger function, the advisory lock, JSONB,
  `FOR UPDATE`, the LangGraph Postgres checkpointer). Compose-based `test` profile; wired into CI.
- **Real Docker sandbox:** run `tests/execution/test_docker_real.py` and the acceptance item 4 for real; add the
  host-path translation (`SANDBOX_HOST_WORKSPACE_ROOT`) so a containerised worker can use the sandbox; an opt-in
  `workers-docker` compose profile behind a docker-socket proxy (create/start/kill/remove only) - not the default.
- **Real identity provider:** OIDC against a local Keycloak container (login, bad-audience, expired, domain restriction).
- **Security gaps:** react-router v7 (clears the last 2 moderate advisories); optional token on the worker metrics port;
  optional backup encryption (`age`/`openssl`).
- **Small ADR limits:** audit login failures; per-model price map (replace the single blended `COST_PER_1K_TOKENS`).
- **Gate 13:** all earlier gates + Postgres suite + real Alembic on Postgres + real Docker sandbox test + Keycloak OIDC
  test + CI green on the pushed commit (the gate records the commit hash it ran on).
- **Needs from you:** Docker daemon running; a GitHub repo with Actions enabled. **Risk:** CI finds failures that were hidden
  locally; budget time for them.

## Phase 14 - Measure it (the real evaluation)
**Goal:** answer the research question with data: does the feedback loop beat single-shot generation, and is it worth the cost?
- Run `make eval` with a real model: E1/E2/E3 (>=3 trials per task, 30 tasks + the 20 Phase 8 tasks), with a spending cap.
  Then ablations A1-A4 and the Phase 9 switches P0-P4 to see which components actually help.
- **Publish honestly:** `docs/evaluation_report.md` with real tables, Wilson/t intervals, cost per solved task, false-accept
  rate, and a written **failure analysis** (which task types fail and why). Reproducible from the manifest (commit, task hash,
  config hash).
- **Act on the evidence:** switches that are "not distinguishable from noise" get removed or kept off by default; routing
  (cheap vs strong model per agent) is tuned from measured cost/quality; the token/iteration defaults are re-derived.
- Add a **regression benchmark**: a small fixed subset that runs in CI against the oracle (cheap) and nightly against the
  real model (budgeted), alerting on drops.
- **Gate 14:** published, reproducible results exist for E1-E3 and the ablations, the report matches `trials.jsonl`
  (checked by a script), and the defaults in the code match the decisions in the report.
- **Needs from you:** an API key, a model name, a spending budget (the dry run prints the worst case first).
  **Risk:** the honest answer may be "the loop helps less than hoped"; that result shapes Phase 16.

## Phase 15 - A product people can use (UX, accounts, notifications)
**Goal:** a new user can sign up, understand it, finish a task and trust the result without help.
- **End-to-end tests in a real browser** (Playwright) against the real stack: sign up, create task, watch the loop, approve a
  gate, read the report, download the zip, org switch, admin page. Accessibility (axe) and mobile-width checks in CI.
- **Accounts that real services need:** email verification, password reset, invitation emails (admin invites by email, link
  accepts), session management page (list/revoke sessions). This also removes the "account pre-registration vs SSO linking"
  caveat by allowing safe linking after verification. Pluggable mail backend (SMTP/SES), console backend for dev.
- **Notifications:** email/webhook/in-app for "task finished", "approval needed", "quota near limit".
- **Guided experience:** onboarding checklist, task templates (CRUD API, auth service, data-validation library), clearer failure
  explanations in the report ("what failed, what the Repair agent tried, what a human should do"), a diff-review UI with inline
  comments for approvals.
- **Per-member quotas** (migration 0009; ceiling = min of org and member remainder) and quota-warning UI.
- **Gate 15:** Playwright suite green in CI, axe has no serious violations on the main screens, email flows tested against a
  mail catcher, quota tests.
- **Risk:** email deliverability and abuse (rate limits, anti-enumeration on reset); treated as security work, not polish.

## Phase 16 - A smarter, broader agent (guided by Phase 14)
**Goal:** raise the *measured* success rate and cut cost per solved task; widen what it can work on.
- **Fix the biggest failure classes from the Phase 14 analysis** (examples to expect: weak planning for multi-file changes,
  flaky or over-specific tests, repairs that oscillate). Each change is a switch with an ablation, as in Phase 9.
- **Repository-scale work:** incremental context (symbol/dependency graph, retrieval over the repo), patch-based edits with
  conflict handling, running only affected tests first then the full suite, caching dependency installs in the sandbox.
- **More languages/frameworks** where Phase 14 shows demand: Go and Java adapters behind the existing `LanguageProfile`
  contract, TypeScript frameworks beyond Jest; images per language, same isolation rules.
- **Better verification:** mutation-style checks on generated tests, property-based test suggestions, coverage of changed
  lines required by the acceptance criteria, security-focused checks (bandit-like per language).
- **Memory that is safe:** per-org retrieval of resolved repairs already exists; add expiry and "do not learn from
  this task" opt-out; evaluate whether it helps (ablation) before enabling by default.
- **Gate 16:** new benchmark tasks per new language/category (>=10 each), the change set shows a statistically
  supported improvement on the held-out tasks or is reported as not helping; cost per solved task does not regress.
- **Risk:** overfitting to the benchmark. Mitigation: hold out tasks that are never used for tuning and are re-run only at
  release time.

## Phase 17 - Trust at scale (security depth, compliance, capacity)
**Goal:** safe to run for other people's code and data, and able to say so with evidence.
- **Independent security review:** external penetration test (or a structured internal one with a checklist and a retest);
  findings tracked and fixed; threat model refreshed for orgs, SSO, integrations, metrics.
- **Stronger isolation:** evaluate gVisor and Firecracker for the sandbox against the current Docker flags (escape-surface
  review, performance cost); ship the chosen runtime behind a setting; egress policy per task (e.g. allow a package mirror
  only); dedicated worker nodes documented as the default for untrusted code.
- **Secrets and data protection:** KMS-backed key management (rotation of the JWT/webhook/integration keys; today HS256 shared
  secret), encryption at rest for integration tokens and backups, per-org data residency settings, DSAR-style export/delete
  beyond the current org export, retention that also covers backups.
- **Enterprise identity:** SSO group -> role mapping, SCIM provisioning, SAML via a broker, domain -> org mapping, enforced MFA
  policy per org.
- **Capacity and resilience:** load tests at realistic concurrency on PostgreSQL, queue back-pressure, worker autoscaling
  validated on a real cluster (KEDA example becomes tested), SLOs with error budgets, tuned alert thresholds, a rehearsed
  disaster-recovery restore with measured RTO/RPO, multi-AZ database guidance.
- **Compliance readiness:** SOC 2-style control mapping (audit log, access reviews, change management), SBOM + signed
  images/provenance (cosign), dependency policy.
- **Gate 17:** pen-test report with all high findings closed; sandbox runtime decision recorded with measurements;
  DR drill with measured RTO/RPO; load test meets stated SLOs; signed images in CI.
- **Needs from you:** budget/time for an external tester; a staging environment.

## Phase 18 - Platform, ecosystem and v1.0
**Goal:** other teams and tools can build on LoopForge; a versioned, supported release.
- **Stable public API:** versioned OpenAPI, API tokens with scopes (exists from Phase 11) hardened, rate limits per token,
  idempotency keys, pagination everywhere, deprecation policy; official Python and TypeScript SDKs; the CLI (exists)
  gets packaging and shell completion.
- **Developer-workflow integrations:** GitHub App (not a PAT) with PR checks that run LoopForge on failing CI, comment-driven
  commands (`/loopforge fix`), GitLab support, Slack/Teams bot using the webhook system, IDE extension for "send this
  failing test to LoopForge".
- **Extensibility:** pluggable agents/tools through a documented interface (custom verifiers, linters, language profiles) with
  the same sandbox and audit guarantees; organization-private task templates and a shared benchmark-task pack format so
  teams can add their own evaluation tasks.
- **Usage metering and plans:** per-org usage reports, exportable CSV/invoice data, configurable plans/limits (billing
  integration optional), cost dashboards by project/user.
- **Release engineering:** semantic versions, changelog, upgrade guides and tested upgrade paths between releases (migration
  playbook from the expand/contract policy), long-term-support policy, docs site with tutorials and an architecture guide,
  reference deployment (Helm chart / Terraform) that is itself tested.
- **Gate 18 / v1.0:** the upgrade test (N-1 -> N with data) passes, SDKs pass contract tests against the live API, the
  reference deployment installs from scratch in CI, docs build without broken links, and the evaluation report is current for
  the release commit.

---

## What carries over (do not throw away)
Deterministic controller and its 100% branch-coverage rule; ablation switches (E/A/P) as the way to justify every feature;
org/role/audit model and the route-matrix completeness test; correlation ids and metrics; chaos/backup/load drills and
`preflight.py`/`provenance.py`; the ADR + gate-script habit; the "Known limits" section in every ADR.

## Order of work and rough effort (one engineer, calendar weeks are a guess)
| Phase | Theme | Effort | Can start when |
|---|---|---|---|
| 13 | Prove it | 1-2 wk | now |
| 14 | Measure it | 1-2 wk (mostly waiting and analysis) | 13 done (or at least Docker + CI) |
| 15 | Real-user product | 3-4 wk | in parallel with 14 |
| 16 | Smarter, broader agent | 4-6 wk | 14 results available |
| 17 | Trust at scale | 4-6 wk (+ external tester lead time) | 13 done; start the pen-test booking early |
| 18 | Platform and v1.0 | 4-6 wk | 14, 15, 17 mostly done |

## Open questions for the owner
1. Budget and key for the real evaluation (Phase 14), and how much per full run you are willing to spend?
2. Who is the first real user (internal team, customers)? It decides how early Phase 15 and 17 matter.
3. Hosted SaaS or self-hosted product? Phase 17/18 scope differs (billing, tenancy hardening vs packaging, upgrades).
4. Which languages matter after Python/JavaScript (Phase 16)?
5. Is an external pen-test affordable, and on what timeline?
