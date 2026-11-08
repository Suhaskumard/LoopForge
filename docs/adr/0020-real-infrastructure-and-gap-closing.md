# ADR-0020: Proving it on real infrastructure, and closing known gaps (Phase 13)

**Status:** accepted (Phase 13). **Principle:** before adding anything new, make what was already written *run*: on PostgreSQL,
in real containers, against a real identity provider. Every check below that cannot run **fails** the gate (no silent skips).

## What running things for real found
| # | Found by | Finding | Fix |
|---|---|---|---|
| 1 | The Phase 12 gate, finally run to completion | **A security regression I introduced:** a `# nosec` comment placed in the middle of a condition swallowed `or len(self.jwt_secret) < 32`, so a production JWT secret shorter than 32 characters was accepted. An existing test caught it. | Condition rewritten with a named constant; the test stays |
| 2 | The same gate | An order-dependent metrics test counted an absolute value in a per-process registry | Counts a delta |
| 3 | Real PostgreSQL | **`TRUNCATE audit_log` erased the "append-only" audit log.** Row triggers do not fire for TRUNCATE; only UPDATE/DELETE were blocked (SQLite has no TRUNCATE, so this was invisible before) | Statement-level `BEFORE TRUNCATE` trigger: model DDL + migration `0009` |
| 4 | Real tools on Windows | GNU tar read `C:/path` as `host:path` in `backup.sh`/`restore.sh` | `--force-local` under Git Bash/Cygwin |
| 5 | `npm audit` on the real registry | 3 HIGH `react-router-dom` advisories (Phase 12), then 2 MODERATE | Upgraded to `react-router` 7.18.5 (React 18 compatible); `npm audit` reports 0. v8 needs React 19 and was not used |

## Decisions
- **PostgreSQL:** a throwaway PostgreSQL 16 (`docker-compose.test.yml`, tmpfs, localhost:5433). `scripts/test_postgres.sh` runs real
  Alembic up/down/up, the PostgreSQL-only tests (`test_phase13_postgres.py`: Alembic vs models drift, migration 0006's data step, the
  audit triggers on both the migration and `create_all` paths, the advisory lock with three *concurrent migration processes*,
  `FOR UPDATE`, JSONB, lease takeover, exclusive job claims, the PostgreSQL LangGraph checkpointer), the real backup/restore scripts,
  and the whole backend suite on PostgreSQL.
- **Real sandbox:** the demo loop runs with the real `DockerSandbox`: pytest fails on the injected defect inside a container and
  passes after the repair; a probe proves the container has no network. Acceptance item 4 is now PASS.
- **Containerised worker (opt-in):** `docker-compose.worker-docker.yml`. The worker has the Docker CLI but not the socket; it talks to
  a docker-socket-proxy (containers only). `SANDBOX_HOST_WORKSPACE_ROOT` translates `/data/workspaces/...` to the host path, because
  the host daemon resolves bind-mount sources on the host. The translation is pure and unit-tested; the end-to-end smoke test
  (`scripts/docker_worker_smoke.sh`) runs a task through worker container -> proxy -> host daemon -> sandbox container.
- **Real identity provider:** Keycloak 26.0.7 with an imported realm. The browser-less authorization-code flow is driven for real:
  login creates the user and personal org, a second login reuses it, wrong password / unverified email / disallowed domain / wrong
  client secret / replayed code are all refused, and ID tokens are verified against Keycloak's real JWKS.
- **Small ADR limits closed:** login failures and rate-limit blocks are audited for *existing* accounts only (unknown addresses
  would let anyone flood the log; the address is stored as a hash), refresh-token reuse is audited; `MODEL_PRICES_JSON` prices each
  agent run at its model's rate in analytics and reports; `WORKER_METRICS_TOKEN` protects the worker metrics port; backups can be
  encrypted (Fernet in the SQLite drill; `openssl` AES-256-CBC + PBKDF2 in the PostgreSQL scripts).

## Known limits
- **Keycloak is one real provider.** Okta, Entra ID and Google differ in claims and quirks; this does not prove them.
- **The socket proxy filters by endpoint, not by content.** Anything that can reach it can still create a container with any bind
  mount or `--privileged`. It is defence in depth. `build_run_args` remains the only trusted source of sandbox arguments, the worker
  must not run untrusted code outside the sandbox, and it belongs on a dedicated node. Never publish port 2375.
- **`openssl enc` gives confidentiality, not integrity.** The checksum manifest detects accidental damage but is itself unsigned; use
  `age` (authenticated encryption) on the output if tampering matters.
- **PostgreSQL:** one single-node container. Failover, replication lag and multi-node behaviour are still untested.
- **GitHub Actions results exist only after a real push.** The jobs were added; nothing has run on GitHub yet.
- **The real model evaluation is Phase 14.** Nothing here measures LoopForge's quality.
- Per-member quotas (planned) were deferred: not needed to prove anything, and the roadmap moves them to Phase 15.
