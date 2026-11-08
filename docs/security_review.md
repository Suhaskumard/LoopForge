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

## Residual risks (not solved)
- **Containers are not a hard boundary.** Docker with the controls in security_model is defence in depth; gVisor or
  Firecracker were not evaluated. Do not run hostile workloads on a shared host.
- **Redaction is pattern-based.** It catches common token shapes and `key=value` forms; an unusual secret format
  passes through. The primary control is not giving agents secrets at all.
- **Prompts go to a third party.** Whatever is not redacted is sent to the LLM provider.
- **WebSocket token in the URL** can land in proxy logs; 15-minute lifetime limits the damage.
- **Refresh token in sessionStorage** is readable by any XSS (ADR-0011); mitigated by CSP and no HTML injection, not removed.
- **No dependency vulnerability scanning**, no SBOM, no signed images.
- **Single shared approver model**: any owner can approve; no separation of duties.
- **CI has never run on GitHub**, and nothing has been penetration-tested by a third party.
- **The real Docker sandbox was not exercised in this environment** unless the acceptance check reports item 4 as PASS.
