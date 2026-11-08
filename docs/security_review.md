# LoopForge - Security review (Phase 6, spec 11.6 work package 6.3)

Scope: the whole platform as built through Phase 6. Method: STRIDE over the trust boundaries, then an executable
test for every control claimed. "Residual" lists what is NOT solved. Controls from earlier phases are in
`security_model.md`; this review adds what Phase 6 changed and re-verifies the rest.

## Trust boundaries
1. Browser <-> API (JWT, CORS, WebSocket token).
2. API <-> LLM provider (prompts leave the machine).
3. Model output -> workspace and database (untrusted structured data).
4. Generated code -> sandbox (untrusted code execution).
5. Operator <-> secrets (`JWT_SECRET`, `OPENAI_API_KEY`).

## Findings and controls
| # | Threat (STRIDE) | Control | Evidence |
|---|---|---|---|
| 1 | Prompt injection from requirement, code, logs, criteria, plan (T, E) | All untrusted text fenced as data under a fixed policy; spoofed delimiters neutralised; output validated by strict schemas | `tests/agents/test_security_suite.py` (5 hostile payloads x 4 agents, fence balance checked) |
| 2 | A fooled model writes outside the project (T, E) | Path rules at schema, workspace and repair-validator level; validate-all-then-write | `test_repair_cannot_be_steered_into_writing_outside_the_project` (5 paths) |
| 3 | A fooled model smuggles a dependency (T, E) | requirements.txt policy checked for Builder and Repair; sandbox has no network/pip | `test_repair_cannot_smuggle_an_unapproved_dependency` |
| 4 | A fooled Reviewer certifies broken code (R, T) | LLM not consulted while tests fail; tool findings override; criteria `met` needs a green run | `test_a_model_cannot_certify_failing_tests`, `test_tool_findings_override_a_glowing_review` |
| 5 | Secret leakage into prompts, logs, DB, reports (I) | `utils/redact.py` on untrusted prompt text, agent summaries/errors, audit events, stored execution logs; idempotent; property-tested | `test_redact.py`, `test_secrets_in_requirement_never_reach_the_model_or_the_database`, `test_execution_logs_are_redacted_before_storage` |
| 6 | Secrets reach generated code (I) | Container gets only three fixed env vars, no `--env-file`, no host mounts beyond the task workspace | `test_no_environment_secret_or_host_path_is_passed_into_the_container` |
| 7 | Arbitrary command execution (E) | Allowlist: pytest/ruff/bandit with fixed flags; no shell; `-p` plugins and paths validated | `test_command_allowlist_blocks_everything_but_pytest_and_ruff` (8 vectors) |
| 8 | Cross-task contamination (T, I) | Per-task workspace; path escape between tasks refused | `test_task_workspaces_are_isolated_from_each_other` |
| 9 | Runaway spend (D) | Server token cap, per-task cap (never above the server's), estimated-cost cap in the Decision Engine (100% branch coverage), iteration/time/repeat limits | `test_phase6_controls.py`, `test_decision_cost.py` |
| 10 | Unattended risky change (T) | Approval gates (plan review, large repair) pause the run; only the owner can decide; rejection escalates | `test_phase6_controls.py` approvals (8 tests), ADR-0013 |
| 11 | False success (R) | Hidden-test evaluation is independent of the loop; false accepts are a recorded metric; report says "NOT accepted" for any non-COMPLETED status | `test_benchmark_harness.py`, `test_escalated_report_never_claims_success_and_says_why` |
| 12 | Documentation agent alters a verdict (T) | Runs only after a terminal state, writes only a `doc` artifact, failure is swallowed | `test_documentation_failure_cannot_change_the_verdict` |
| 13 | Benchmark tooling executes untrusted code on the host (E) | `HostSandbox` is wired only to the oracle provider (trusted reference code); the real-model branch uses Docker or refuses | `test_host_sandbox_is_only_wired_to_the_oracle_provider` |

## Defect found and fixed during the review
- `GET /tasks/{id}/plan` returned 404 after any repair (the latest iteration has no plan). Found by the acceptance
  check; fixed; regression test `test_plan_endpoint_survives_repair_iterations`.

## Phase 8 - untrusted repositories
New trust boundary: a user-supplied repository (zip or git URL) becomes model input and sandbox input. Controls and
residual risks are in ADR-0015; tests: `tests/unit/test_phase8_languages_and_import.py` (zip-slip, symlink,
bomb, limits, git option/scheme injection, non-public hosts, secret exclusion) and `tests/integration/test_phase8_repo_flow.py`
(a leaked key never appears in any recorded prompt). Not covered: DNS rebinding between the address check and the
clone, and secret formats outside the pattern list.

## Phase 12 additions (operations and supply chain)
Method: ran the scanners that exist locally, fixed what they found, wrote down what remains. Items marked
**(CI only)** were written into `.github/workflows/ci.yml` but could not be run in the development environment.

| # | Finding / control | Result | Evidence |
|---|---|---|---|
| 12.1 | **Dependency vulnerabilities (frontend)**: `npm audit` reported 3 HIGH advisories (open redirect, XSS via open redirect) in `react-router-dom` 6.28.0 / `@remix-run/router` | **Fixed**: `react-router-dom` 6.30.6 (same major). Two MODERATE advisories remain (open redirect via backslash in `<Link>`/`useNavigate`; SSR-only deserialisation) and need a breaking jump to v7. LoopForge navigates only to fixed internal paths and has no SSR, so the exposure is low, but it is **not** closed | `scripts/security_scan.sh`, `test_frontend_does_not_pin_the_react_router_versions_with_high_advisories` |
| 12.2 | **Static analysis**: bandit over `backend/app` | 0 HIGH, 0 MEDIUM. Two MEDIUM findings were resolved (metrics server bound to all interfaces by default -> now `127.0.0.1` unless `WORKER_METRICS_HOST` says otherwise; a false positive on the sandbox's *in-container* `/tmp` tmpfs). 21 LOW remain, accepted: `assert` used for type narrowing after a lookup that was just validated (13), `subprocess` with fixed argv and no shell in the sandbox and repo import (7; Phase 17 added the `docker info` runtime query), the `'change-me'` default that the production validator rejects (1) | `test_bandit_finds_nothing_at_medium_or_high_severity`, `test_bandit_low_findings_do_not_grow_unnoticed` (budget 21) |
| 12.3 | **Python dependency vulnerabilities**: pip-audit on `requirements-runtime.txt`; **SBOMs** (CycloneDX); **image scan** (Trivy, HIGH/CRITICAL) | **(CI only)** - not run here, so no claim about the current state of the Python dependencies | `supply-chain` job; `test_ci_runs_the_security_and_resilience_checks` |
| 12.4 | **Production image shipped test/lint/type tools** (pytest, ruff, mypy, bandit, hypothesis) | **Fixed**: the image installs `requirements-runtime.txt` only; a test proves every third-party import in `app/` is covered by it | `test_every_third_party_import_in_app_is_covered_by_the_runtime_requirements` |
| 12.5 | **Migration race** (every replica ran `alembic upgrade head` on start) could corrupt or fail a rolling deploy | **Fixed**: one-shot `migrate` service, PostgreSQL advisory lock (untested on PostgreSQL here) | `test_phase12_reliability.py` |
| 12.6 | **Metrics exposure**: `/metrics` shows activity levels (no user data, no ids) | Off by default; bearer token when `METRICS_TOKEN` is set; route *templates* only, so ids never become labels. The worker metrics port has **no authentication**: restrict it with network policy | `test_phase12_observability.py` |
| 12.7 | **Backups hold sensitive data** (password hashes, encrypted integration tokens, audit trail, generated code) | `restore` verifies checksums first and refuses archives with absolute or `..` paths; **encrypt and access-control the backup location yourself** (the scripts do not encrypt). Retention does not reach into backups | `backup_drill.py`, `test_restore_refuses_archives_that_escape_the_target_directory` |
| 12.8 | **CI privileges**: workflow token could write to the repository | `permissions: contents: read`; third-party actions pinned to versions | `test_ci_actions_are_pinned_to_a_version` |

## Phase 13 additions (real infrastructure)
| # | Finding / control | Result | Evidence |
|---|---|---|---|
| 13.1 | **Short JWT secrets were accepted in production** (a `# nosec` comment in the middle of a condition swallowed the length check; introduced in Phase 12) | **Fixed**, found by the Phase 12 gate | `test_production_requires_strong_secret` |
| 13.2 | **`TRUNCATE audit_log` wiped the append-only log on PostgreSQL** (row triggers do not fire for TRUNCATE) | **Fixed**: statement-level trigger, migration 0009 | `test_the_database_itself_refuses_to_change_or_delete_audit_rows` (real PostgreSQL) |
| 13.3 | `react-router` advisories (2 MODERATE left after 12.1) | **Fixed**: v7.18.5; `npm audit` = 0 | `npm audit --omit=dev` |
| 13.4 | The sandbox's isolation was only reasoned about | **Exercised for real**: the demo loop runs in containers (the injected defect fails, the repair passes) and a probe shows **no network** inside; acceptance item 4 = PASS | `test_phase13_docker_loop.py`, `acceptance_check.py` |
| 13.5 | SSO verification was tested only against a scripted provider | **Real Keycloak**: login, reuse, wrong password, unverified email, disallowed domain, wrong client secret, replayed code, real JWKS/RS256 | `test_phase13_oidc_keycloak.py` |
| 13.6 | Login failures, rate-limit blocks and refresh-token reuse were invisible in the audit log | Audited for existing accounts only (unknown addresses would let anyone flood the log); the address is stored as a hash | `test_phase13_hardening.py` |
| 13.7 | A containerised worker needed the Docker daemon | Opt-in profile behind a **docker-socket-proxy** (containers only). **Residual:** the proxy filters by endpoint, not by content; it does not make the worker trustworthy | ADR-0020, `test_phase13_gate_files.py` |
| 13.8 | Backups were plaintext | Optional encryption (Fernet in the drill, `openssl` in the PostgreSQL scripts). **Residual:** confidentiality only, the manifest is unsigned | `test_phase13_backup_scripts.py`, `backup_drill.py --encrypt` |

### Sandbox flag review (analysis, not a proof)
`build_run_args` (`execution/sandbox.py`) starts each run with: `--network none`, a non-root UID, `--read-only`
root filesystem, a `noexec,nosuid` tmpfs for `/tmp`, `--cap-drop ALL`, `no-new-privileges`, memory (= swap), CPU and
PID limits, `nofile` ulimit, the workspace bind-mounted **read-only**, and one writable output directory. Observations:
- No custom seccomp/AppArmor profile (Docker's default applies), no user-namespace remapping, no gVisor/Firecracker.
- The writable output directory is world-writable on purpose (the unprivileged sandbox user must write reports into
  it); generated code can therefore put arbitrary bytes there. The host only *parses* it (pytest JSON report, size and
  trace length capped), never executes it.
- A container escape through a kernel or runtime vulnerability is **not** prevented by any of these flags. The
  mitigation is operational: dedicated hosts for workers, patched Docker, and evaluating gVisor/Firecracker.

## Phase 17 additions (trust at scale)
Threat model refresh for the surfaces added since Phase 6 (STRIDE; evidence is an executable test).
| # | Threat | Control | Evidence |
|---|---|---|---|
| 17.1 | One leaked symmetric key exposes every stored secret and forges tokens (I, S) | Key ring with `kid`, separate encryption key required in production, rotation CLI, missing key is a loud error | `tests/unit/test_phase17_keyring.py`, `tests/integration/test_phase17_secrets_rotation.py` |
| 17.2 | Webhook secret read from the database or never rotated (I) | Encrypted at rest, rotation with dual-signature overlap | `test_the_signing_secret_is_not_stored_in_the_clear`, `test_rotation_signs_with_both_secrets_during_the_overlap_then_only_the_new` |
| 17.3 | A tenant's IdP grants itself access to another tenant (E) | SCIM token bound to one org; deprovisioning is per org | `test_unknown_users_are_404_and_other_orgs_users_are_invisible` |
| 17.4 | SSO/SCIM removes or demotes the last admin, locking an org out (D) | Last-admin guard in both paths, audited | `test_the_last_admin_is_never_demoted_or_removed_by_sso`, `test_the_last_admin_cannot_be_deprovisioned_or_demoted` |
| 17.5 | Stolen password alone gives access (S) | TOTP step-up, replay refused, hashed single-use recovery codes, rate limited, org `require_mfa` | `tests/integration/test_phase17_mfa.py` |
| 17.6 | Container escape from a shared kernel (E) | Optional gVisor/Kata runtime, fail closed, production guard (isolation **not measured here**) | `tests/unit/test_phase17_sandbox_runtime.py` |
| 17.7 | A burst of starts overwhelms workers and the database (D) | Global and per-org back-pressure with 429 + `Retry-After` | `tests/integration/test_phase17_backpressure.py` |
| 17.8 | Loss of the database host (D) | Backups, DR drill with measured RTO/RPO | `scripts/dr_drill.py`, `docs/dr_drill_result.json` |

## Residual risks (not solved)
- **Containers are not a hard boundary.** Docker with the controls in security_model is defence in depth; Phase 17 added a
  `SANDBOX_RUNTIME` option for gVisor/Kata but neither is installed here, so their isolation and cost are **unmeasured**; Firecracker was not evaluated. Do not run hostile workloads on a shared host.
- **Redaction is pattern-based.** It catches common token shapes and `key=value` forms; an unusual secret format
  passes through. The primary control is not giving agents secrets at all.
- **Prompts go to a third party.** Whatever is not redacted is sent to the LLM provider.
- **WebSocket token in the URL** can land in proxy logs; 15-minute lifetime limits the damage.
- **Refresh token in sessionStorage** is readable by any XSS (ADR-0011); mitigated by CSP and no HTML injection, not removed.
- **Dependency scanning:** `npm audit` is at 0 (Phase 13); `pip-audit` is run by the Phase 13 gate. SBOMs, the Trivy image scan and signed images are configured/absent and have never run on a real CI runner.
- **Approver model (Phase 10)**: approvals now need the *approver* role and record who decided; there is still no rule preventing the person who started a task from approving it (no separation of duties).
- **CI has never run on GitHub**, and nothing has been penetration-tested by a third party. Phase 12 added tooling, not an external test.
- **The real Docker sandbox was not exercised in this environment** unless the acceptance check reports item 4 as PASS.
