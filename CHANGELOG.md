# Changelog

All notable changes to LoopForge. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) as defined for this project in `docs/api_policy.md`.
Schema heads are the Alembic revision at that release (`docs/schema_baselines.json`).

## [Unreleased]

## [1.0.0-rc1] - 2026-11-08 (release candidate; **not** a 1.0.0 - see ADR-0025)
Schema head: `0013`. Upgrade from the Phase 16 schema (`0011`): `docs/upgrade_guide.md`.

### Added
- **Public API contract**: one version (`app/version.py`), a committed OpenAPI snapshot (`docs/openapi.json`) that fails the build when
  the API changes unnoticed, a breaking-change detector against the Phase 17 baseline, deprecation headers (`Deprecation`, `Sunset`, `Link`).
- **Per-token and per-user rate limits** (`API_TOKEN_RATE_LIMIT_PER_MINUTE`, `USER_RATE_LIMIT_PER_MINUTE`) with `X-RateLimit-*` and `Retry-After`.
- **Idempotency keys** (`Idempotency-Key`) on `POST /projects`, `/tasks`, `/tasks/{id}/start`, `/tasks/{id}/publish`.
- **Pagination everywhere**: `limit`/`offset` plus `X-Total-Count` and `Link: rel="next"` on every collection that can grow.
- **Usage reports** (`/orgs/{org}/usage/report[.csv]`) by project, member, agent, model or day; **plans** (`PLANS_JSON`, `loopforge ops set-plan`).
- **SDKs**: Python (`sdk/python`) and TypeScript (`sdk/typescript`), tested against the real server.
- **CLI packaging**: `pip install ./backend` provides `loopforge` (`--version`, shell completion; `keys`/`ops` with the `server` extra).
- **Upgrade test** (`scripts/upgrade_test.py`): data written under the previous schema survives the upgrade, on SQLite and PostgreSQL.
- Phase 17 ("trust at scale"): key ring and rotation, encrypted webhook secrets with rotation, SSO group mapping, SCIM 2.0, TOTP MFA,
  sandbox runtime option (gVisor/Kata, fails closed), queue back-pressure, SLOs with burn-rate alerts, DR drill, control mapping.
  See `docs/adr/0024-trust-at-scale.md`.

### Changed
- `GET /health` now also returns `version`.
- Production now **requires** `SECRETS_KEY` or `KEYRING_JSON` (and `SECRETS_KEY` must differ from `JWT_SECRET`).
- Metrics route labels keep the `/api/v1` prefix again (they had lost it with the FastAPI upgrade).
- FastAPI 0.162 / Starlette 1.10 / PyJWT 2.15 / cryptography 50 / python-multipart 0.0.33; react-router 7.18 (Phase 13 dependency upgrade).

### Deprecated
- Nothing yet.

### Security
- Secrets (git tokens, webhook secrets, TOTP seeds) are encrypted under a rotatable key; access tokens carry the key id.
- Known gaps: no external penetration test; the signed-release workflow has never run (ADR-0024, ADR-0025).

## Earlier phases (pre-release, no tags)
- **Phase 16** - smarter, broader loop: default-off switches Q1-Q5, patch edits, affected-tests-first, Go adapter, held-out split (ADR-0023). Schema `0011`.
- **Phase 15** - product: email verification, password reset, invitations, sessions page, notifications, per-member quotas (ADR-0022). Schema `0010`.
- **Phase 14** - measurement tooling; the real-model run is still to be done (ADR-0021).
- **Phase 13** - proved on real PostgreSQL, Docker and Keycloak; found and fixed real defects (ADR-0020). Schema `0009`.
- **Phase 12** - observability, backups, supply-chain scanning (ADR-0019). Schema `0008`.
- **Phases 1-11** - the loop, sandbox, dashboard, orgs/roles/SSO, integrations (ADR-0001 to ADR-0018).
