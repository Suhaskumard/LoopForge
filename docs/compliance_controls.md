# Control mapping (Phase 17)

A map from common control objectives (SOC 2 Trust Services Criteria style) to **the artifact that is the evidence**. It is a readiness aid,
**not an attestation**: no audit has been performed, no auditor has reviewed it, and organisational controls (HR, vendor management,
physical security, board oversight) are outside what a codebase can show. `test_phase17_compliance_docs.py` fails if any path or test
named below stops existing, so this table cannot silently rot.

Evidence column: `file` = a path in the repository; `test::name` = a test function; `gate` = a script that runs it.

| Control objective | What LoopForge does | Evidence |
|---|---|---|
| **CC6.1** Logical access: authentication | Password (bcrypt) + optional TOTP MFA; OIDC SSO with PKCE/state/nonce against JWKS; short-lived access tokens + rotating refresh tokens with reuse detection | `backend/app/services/mfa_service.py`; `backend/tests/integration/test_phase17_mfa.py::test_login_step_up_requires_a_valid_code`; `backend/tests/integration/test_phase10_oidc.py`; `backend/tests/integration/test_phase15_accounts.py` |
| **CC6.1** Credential storage | Secrets encrypted under a rotatable key ring; refresh tokens and API/SCIM tokens stored only as hashes | `backend/app/utils/keyring.py`; `backend/tests/unit/test_phase17_keyring.py::test_new_writes_use_the_active_key_and_old_values_stay_readable`; `backend/tests/integration/test_phase17_secrets_rotation.py::test_the_signing_secret_is_not_stored_in_the_clear` |
| **CC6.2 / CC6.3** Provisioning, role-based access, least privilege | Four roles read from the database per request; route-authorization matrix with a completeness check; SSO group mapping; SCIM provisioning and deprovisioning | `backend/tests/integration/test_phase10_authz.py::test_every_route_is_in_the_matrix`; `backend/tests/integration/test_phase17_scim.py::test_delete_deprovisions_and_ends_sessions_immediately`; `backend/tests/integration/test_phase17_sso_mapping.py::test_the_last_admin_is_never_demoted_or_removed_by_sso` |
| **CC6.6** Boundary protection | Sandbox: no network, read-only, non-root, capabilities dropped, resource limits, optional gVisor/Kata runtime that fails closed | `backend/app/execution/sandbox.py`; `backend/tests/unit/test_phase17_sandbox_runtime.py::test_missing_runtime_fails_closed`; `docs/security_model.md` |
| **CC6.7** Data in transit / at rest | TLS is the deployer's reverse proxy (documented); secrets and TOTP seeds encrypted at rest; encrypted backups | `docs/operations.md`; `backend/tests/integration/test_phase13_backup_scripts.py` |
| **CC6.8** Malicious software | Untrusted repositories handled under a policy (no hooks, no network, size limits); model output validated by schemas | `backend/tests/agents/test_security_suite.py`; `docs/security_review.md` |
| **CC7.1** Vulnerability management | pip-audit / npm audit / bandit gate; Dependabot; dependency policy | `scripts/security_scan.sh`; `docs/dependency_policy.md`; `.github/dependabot.yml` |
| **CC7.2** Monitoring | JSON logs with request/task/job ids; Prometheus metrics; alert rules including SLO burn rates | `deploy/observability/alerts.yml`; `backend/tests/integration/test_phase12_observability.py::test_every_metric_in_alerts_dashboard_and_autoscaling_exists`; `docs/slo.md` |
| **CC7.2 / CC7.3** Audit trail | Append-only audit log enforced by database triggers (also TRUNCATE on PostgreSQL); security events audited | `backend/tests/integration/test_phase10_governance.py::test_the_audit_log_is_append_only_at_the_database_level`; `backend/tests/integration/test_phase13_postgres.py`; `docs/dr_drill_result.json` |
| **CC7.4 / CC7.5** Incident response and recovery | Incident checklist; runbooks per alert; DR drill with measured RTO/RPO | `docs/operations.md`; `scripts/dr_drill.py`; `docs/dr_drill_result.json` |
| **CC8.1** Change management | Every phase ends in a gate; CI on push; ADRs for decisions; migrations tested up and down on SQLite and PostgreSQL | `scripts/phase17_gate.sh`; `.github/workflows/ci.yml`; `docs/adr/0024-trust-at-scale.md`; `backend/tests/integration/test_migrations.py` |
| **CC9.2** Vendor / supply chain | Pinned dependencies, SBOMs, image scan; signed images with provenance (written, unverified) | `.github/workflows/release.yml`; `scripts/verify_image.sh`; `docs/dependency_policy.md` |
| **A1.1 / A1.2** Availability and capacity | SLOs with error budgets; back-pressure; autoscaling definition; worker crash recovery | `docs/slo.md`; `backend/tests/integration/test_phase17_backpressure.py::test_global_cap_refuses_with_retry_after_and_leaves_the_task_startable`; `scripts/chaos_drill.py` |
| **A1.3** Recovery testing | Backup/restore on real PostgreSQL; DR drill | `scripts/backup.sh`; `scripts/restore.sh`; `scripts/dr_drill.py` |
| **C1.1 / C1.2** Confidentiality, disposal | Tenant isolation tests; retention, export and delete-all-data; PII redaction option | `backend/tests/integration/test_phase10_authz.py::test_organization_b_cannot_see_or_touch_organization_a`; `backend/tests/integration/test_phase10_governance.py::test_retention_purges_only_old_finished_tasks_and_their_files` |
| **P-series** Privacy | Member-level quotas visible to the member; memory opt-out per task (`learn_from_task`); export and deletion per organization | `backend/tests/integration/test_phase10_governance.py::test_export_is_complete_and_free_of_secrets`; `docs/adr/0023-smarter-broader-loop.md` |

## Not covered by this repository (needs the organisation)
Policies and training, background checks, vendor reviews, risk register ownership, business-continuity plan sign-off, physical and
network controls of the hosting environment, an independent audit (SOC 2 Type I/II) and an **external penetration test**
(`docs/pentest/` prepares one; none has been done).
