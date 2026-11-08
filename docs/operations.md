# LoopForge operations guide (Phases 12-13)

Audience: whoever deploys and runs LoopForge. Design decisions and limits: ADR-0019 (operations) and ADR-0020
(proving it on real infrastructure). Phase 13 ran PostgreSQL 16, the real Docker sandbox, Keycloak and the backup/restore
scripts for real; what is still **(untested here)** is marked: a Kubernetes cluster, PostgreSQL failover/replication,
the other identity providers (Okta, Entra ID, Google) and a live GitHub.

## Processes and what to watch
| Process | Command | Scrape |
|---|---|---|
| API | `uvicorn app.main:app` | `GET /metrics` when `METRICS_ENABLED=true` (+ `METRICS_TOKEN`) |
| Worker (any number) | `python -m app.worker` (`RUN_MODE=queue` on the API) | `WORKER_METRICS_PORT=9100` serves `/metrics` for that process |
| Database | PostgreSQL 16 | your usual exporter |

Counters and histograms live **per process**: scrape the API and every worker. Gauges for shared state (tasks by
status, queue depth, leases, tokens this month) are computed from the database at scrape time and are the same from
any API replica. Alert rules, a Grafana dashboard and an autoscaling example are in `deploy/observability/`.

## Logs and correlation ids
JSON lines on stdout. Every line has `request_id`; lines produced while a job or task is processed also have `job_id`
and `task_id`. The API stores the request id on the job, and the worker logs with it, so
`grep <request id>` follows one action from the HTTP request to the worker that ran it. Send your own
`X-Request-ID` to correlate with a gateway. There is no distributed-tracing backend: the ids are in logs only.

## Configuration that matters in production
`ENVIRONMENT=production` (refuses the default JWT secret, the fake LLM and the fake sandbox, and any `MAIL_BACKEND` other than `smtp`), `RUN_MODE=queue`,
`TRUSTED_PROXY_COUNT`, `METRICS_ENABLED`/`METRICS_TOKEN`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`DB_POOL_RECYCLE_SECONDS`, `DB_POOL_PRE_PING` (default on: a connection killed by a DB failover is replaced instead of
failing the request), `LEASE_TTL_SECONDS`, `MAX_TOKEN_BUDGET`. See `.env.example`.

## Deploy
```bash
cp .env.example .env            # set JWT_SECRET (32+ chars), OPENAI_*, METRICS_TOKEN, ...
docker compose up -d --build db
docker compose run --rm migrate # one-shot: alembic upgrade head (advisory-locked on PostgreSQL)
docker compose --profile workers up -d --build
```
Migrations run **once**, in the `migrate` service, never in every replica's start command (they used to race). The
backend waits for it to complete. Three simultaneous `alembic upgrade head` processes on an empty PostgreSQL were tested
and all succeed (the advisory lock serialises them).

## Zero-downtime migration policy
Deploy in two steps so old and new code can run side by side during a rolling update:
1. **Expand** (release N): add nullable columns / new tables / new indexes only; code writes both shapes.
2. **Contract** (release N+1, after N is everywhere): drop or rename old columns, tighten constraints.
Never combine an expand and a contract in one release, and never run `alembic downgrade` on production data without
a backup (see below). Every migration must keep `test_migrations.py` green (models and migrations must match, and
the downgrade must be clean).

## Workers that run the real sandbox in containers (opt-in)
The default `worker` service does not have a Docker daemon, so it cannot run the real sandbox. For that, use the opt-in file:
```bash
export LF_HOST_WORKSPACES=/srv/loopforge/workspaces      # a HOST directory, absolute path
docker build -t loopforge-sandbox backend/sandbox         # the image must exist on the host daemon
docker compose -f docker-compose.yml -f docker-compose.worker-docker.yml --profile workers-docker up -d --build
```
The worker image has the Docker CLI but **not** the socket: it talks to a `docker-socket-proxy` that allows containers only
(no images, volumes, networks, exec, build, swarm). The API and the worker share `LF_HOST_WORKSPACES` as a host bind, and
`SANDBOX_HOST_WORKSPACE_ROOT` translates the worker's `/data/workspaces/...` into that host path, because the host daemon
resolves bind-mount sources on the host. **The proxy filters by endpoint, not by content**: anything that reaches it can still
create a container with arbitrary binds. Keep the worker on a dedicated node, never publish port 2375, and treat the worker as
trusted code. `scripts/docker_worker_smoke.sh` runs the whole chain once (worker container -> proxy -> host daemon -> sandbox
container) and is part of the Phase 13 gate.

## Scaling workers
The unit of work is one task run (minutes). Queue depth is `loopforge_jobs_queued`, and the age of the oldest waiting
job is `loopforge_jobs_oldest_queued_age_seconds`. Add workers when the age alert fires; `deploy/observability/
keda-worker-scaledobject.yaml` is an **example (untested here)** that scales on queued + running jobs with a long
cooldown so a worker finishing a run is not removed mid-iteration. Each worker needs Docker access for the sandbox
(see ADR-0008): the compose file does not grant it by default.

## Worker crash recovery
A run holds a lease that its worker renews. If the worker is killed (`kill -9`, node loss), the lease expires
(`LEASE_TTL_SECONDS`), another worker's recovery scan queues a resume, and the run continues **from its checkpoint**
without repeating completed agent steps. You will see `lease takeover` in the logs and
`loopforge_lease_takeovers_total` increase: that is expected after a crash or deploy. A persistent
`loopforge_expired_leases > 0` means recovery is not happening: check that at least one worker is running and
connected to the same database.
`python scripts/chaos_drill.py` proves this end to end (real process, `SIGKILL`, takeover, task completes).

## Backup and restore
What to back up: the database and the workspaces directory (generated code, logs). The audit log is in the database.
- PostgreSQL: `scripts/backup.sh` (pg_dump custom format + workspaces tarball) and `scripts/restore.sh`, run for real in
  Phase 13 against PostgreSQL 16 (round trip, corruption refused, encryption, wrong/missing key). Test a restore on a scratch
  database regularly: an untested backup is a hope.
- SQLite (development only): `python scripts/backup_drill.py` backs up, wipes, restores and verifies row counts and the
  audit log; add `--encrypt` to prove the key matters. Both are part of the gates.
- **Encryption (optional):** `BACKUP_PASSPHRASE_FILE=/path/to/passphrase` makes `backup.sh` encrypt both artifacts with `openssl`
  (AES-256-CBC, PBKDF2) and leave no plaintext copy; `restore.sh` needs the same variable and refuses a missing or wrong one.
  This is confidentiality, not integrity: the checksum manifest catches accidental damage but is not signed (use `age` on the
  output if tampering matters). Keep the passphrase somewhere other than next to the backup.
- **Running the PostgreSQL scripts against a container:** set `PG_CONTAINER=<name>` and `pg_dump`/`pg_restore` run inside it
  (no client tools needed on the host). `bash scripts/test_postgres.sh` exercises both scripts against a throwaway server.
Retention (`retention_days`) deletes data from the database and workspaces but **not** from your backups: remember that
when promising deletion.

## Database failover
Pooled connections are tested before use (`pool_pre_ping`) and recycled (`pool_recycle`), so after a failover the first
requests may fail while the pool heals and then recover on their own. Workers that lose the database retry their
loop; a task interrupted by the outage resumes from its checkpoint. **(PostgreSQL failover untested here.)**

## Cost and quotas
Per-organization monthly quotas are enforced server-side (ADR-0017); `loopforge_tokens_used_month` is the total across
organizations. Token counts are estimates from agent runs, not billing data: reconcile with your provider's invoice.

## Incident checklist
1. `GET /health/ready` (database) and `/metrics`; check the dashboard panels for requests, queue age, leases.
2. **5xx spike**: find the `request_id` in a failing response (`X-Request-ID`), grep the logs for it, read the `exc`.
3. **Queue growing**: are workers alive (`loopforge_jobs_running`, worker logs)? Scale up, or look for a stuck
   dependency (provider outage -> `LoopForgeModelFailures`; Docker/image problem -> `LoopForgeSandboxInfrastructureErrors`).
4. **Stalled runs**: see *Worker crash recovery*.
5. **Sandbox infrastructure errors**: the loop deliberately does not "repair" code when the sandbox itself cannot run;
   fix Docker/the image, then use *retry* on the affected tasks.
6. After the incident: note the request ids, the timeline and what alert would have caught it sooner.

## Running the tests on real infrastructure
`bash scripts/test_postgres.sh` starts a throwaway PostgreSQL 16 (`docker-compose.test.yml`, tmpfs, localhost:5433), runs real
Alembic up/down/up, the PostgreSQL-only tests and the whole backend suite on it, then removes it (`PG_SUITE=quick` skips the
long part; `KEEP_DB=1` keeps the container). `bash scripts/test_keycloak.sh` does the same for a real Keycloak (OIDC).
`pytest -m docker` runs the real-sandbox tests. These scripts **fail** without a Docker daemon instead of skipping.

## Real evaluation
See `docs/evaluation_report.md`. `make eval` runs the preflight (key, model, Docker, images, cost ceiling) and then the
benchmark. No results exist until it has run.
