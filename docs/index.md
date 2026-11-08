# LoopForge documentation

LoopForge turns a plain-language requirement into tested code with an automated, feedback-driven loop: plan, build, run the tests in a locked-down
sandbox, review, repair, repeat - under a deterministic controller with budgets, approvals and an audit trail. This is release candidate
**1.0.0-rc1**: read [what blocks a 1.0.0](releasing.md#what-blocks-a-100-as-of-the-release-candidate) before depending on it.

## Start here
* [Quickstart](tutorials/quickstart.md) - run it locally and complete a first task.
* [Use the API and the SDKs](tutorials/api_and_sdks.md) - tokens, idempotent creates, pagination, rate limits, usage reports.
* [Set up SSO, SCIM and MFA](tutorials/identity_setup.md) - enterprise sign-in and provisioning.
* [Operate it](tutorials/operating.md) - deploy, back up, rotate keys, upgrade, respond to alerts.

## Reference
* [API documentation](api_documentation.md) and [API policy](api_policy.md) (versioning, deprecation, limits); the machine-readable contract is `docs/openapi.json`.
* [Architecture](architecture.md), [database schema](database_schema.md), [operations guide](operations.md), [SLOs](slo.md).
* [Security model](security_model.md), [security review](security_review.md), [dependency policy](dependency_policy.md), [control mapping](compliance_controls.md).
* [Penetration-test scope](pentest/scope.md) and [finding template](pentest/findings_template.md) (no external test has been done).
* [Evaluation report](evaluation_report.md) - the honest state of the measurements ("To be measured" means exactly that).
* [Demo runbook](demo_runbook.md).

## Releases
* [Changelog](../CHANGELOG.md), [upgrade guide](upgrade_guide.md), [support policy](support_policy.md), [releasing](releasing.md).
* Roadmaps: [phases 8-12](roadmap_phases_8_12.md), [phases 13-18](roadmap_phases_13_18.md). The project [README](../README.md).

## Architecture decisions
Every significant decision has an ADR with a "Known limits" section:
[0001 modular monolith](adr/0001-modular-monolith.md),
[0002 LangGraph](adr/0002-langgraph.md),
[0003 PostgreSQL JSONB](adr/0003-postgres-jsonb.md),
[0004 deterministic controller](adr/0004-deterministic-controller.md),
[0005 SQLite for fast tests](adr/0005-sqlite-for-fast-tests.md),
[0006 session model](adr/0006-session-model.md),
[0007 LLM client abstraction](adr/0007-llm-client-abstraction.md),
[0008 Docker CLI sandbox](adr/0008-docker-cli-sandbox.md),
[0009 checkpoints](adr/0009-persistent-checkpoints-idempotent-nodes.md),
[0010 event stream](adr/0010-db-polled-websocket-events.md),
[0011 frontend stack](adr/0011-frontend-stack-and-token-storage.md),
[0012 benchmark design](adr/0012-benchmark-design.md),
[0013 approval gate](adr/0013-human-approval-gate.md),
[0014 workers and leases](adr/0014-worker-service-leases-and-job-queue.md),
[0015 language profiles](adr/0015-language-profiles-and-repository-input.md),
[0016 smarter loop](adr/0016-smarter-loop.md),
[0017 organizations, roles, SSO](adr/0017-organizations-roles-and-sso.md),
[0018 integrations](adr/0018-integrations-and-delivery.md),
[0019 operations and evaluation kit](adr/0019-production-operations-and-evaluation-kit.md),
[0020 real infrastructure](adr/0020-real-infrastructure-and-gap-closing.md),
[0021 measurement tooling](adr/0021-measurement-tooling.md),
[0022 product experience](adr/0022-product-experience.md),
[0023 smarter, broader loop](adr/0023-smarter-broader-loop.md),
[0024 trust at scale](adr/0024-trust-at-scale.md),
[0025 platform and release candidate](adr/0025-platform-and-release-candidate.md).
