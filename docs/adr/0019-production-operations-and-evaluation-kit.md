# ADR-0019: Production operations and the real-evaluation kit (Phase 12)

**Status:** accepted (Phase 12). **Scope decision (owner):** build everything that can be built and *proved* in the
development environment; for the rest ship tooling and runbooks and **claim nothing**.

## Decision
### Observability (no new dependency)
- **Correlation ids.** Every JSON log line carries `request_id`; lines produced while a job or task is processed also
  carry `job_id` and `task_id` (ContextVars; `thread_target` carries them across threads such as the lease heartbeat).
  The API stores the request id on the job (`jobs.request_id`, migration 0008) and the worker restores it, so one id links
  an HTTP request to the worker that ran it. This also fixed a bug: the access-log line used to print `request_id: "-"`.
  There is no tracing backend; the ids live in logs.
- **Metrics.** A hand-written Prometheus registry (`utils/metrics.py`), `GET /metrics` (off unless `METRICS_ENABLED`,
  bearer token when `METRICS_TOKEN` is set) and, for workers, a stdlib server on `WORKER_METRICS_PORT` (bound to
  `127.0.0.1` unless `WORKER_METRICS_HOST` says otherwise). HTTP series are labelled by route **template**, never by raw
  path or id. Counters and histograms are per process (scrape the API and each worker); gauges for shared state (tasks by
  status, queue depth and age, active/expired leases, tokens this month) are computed from the database at scrape time.
- **Alerts, dashboard, autoscaling** are files under `deploy/observability/`. A test fails if any of them names a metric
  that does not exist, and if an alert's runbook link points at a heading missing from `docs/operations.md`.
  Thresholds are starting points, not tuned values. The KEDA manifest is an untested example.

### Reliability
- DB engines use `pool_pre_ping`, `pool_recycle` and a bounded pool (server databases), so a restarted or failed-over database
  heals instead of failing every request until restart. (Behaviour under a real PostgreSQL failover is untested here.)
- Migrations run **once per release** in a `migrate` service under a PostgreSQL advisory lock; the image no longer runs them
  on every start (`RUN_MIGRATIONS=1` for a single-container deployment). Compose gained restart policies, a backend
  healthcheck, a shared `workspaces` volume and resource limits. The image installs `requirements-runtime.txt` only.
- **Drills that actually run:** `scripts/chaos_drill.py` starts a real worker process, kills it mid-task and shows another
  worker taking over the expired lease and finishing from the checkpoint without repeating the Planner;
  `scripts/backup_drill.py` backs up, wipes and restores a SQLite deployment and verifies counts, audit trail, workspace
  files and the append-only triggers, and shows a corrupted backup is refused; `scripts/load_test.py` drives concurrent users
  against a live server and fails on any 5xx or any cross-user leak (latency is reported, not judged). `backup.sh` and
  `restore.sh` do the same for PostgreSQL and were **not run**.
- The slow fake LLM (`FAKE_LLM_DELAY_SECONDS`, fake provider only) answers by request type, not queue order, so a fresh
  process can resume a half-finished run.

### Security hardening
Bandit runs in CI (`-ll`: medium and above fails) and locally; the two medium findings were fixed or shown to be false
positives. `npm audit` found three HIGH advisories in `react-router-dom`; they are fixed (6.30.6). CI also has pip-audit,
SBOM generation and a Trivy image scan, with least-privilege `permissions` and pinned actions: those jobs were **never run
here**. The sandbox flags were reviewed in writing (not proved). See `docs/security_review.md`, "Phase 12 additions".

### Real-evaluation kit
`benchmarks/preflight.py` lists **every** blocker (key, model, explicit price per 1k tokens, spending cap, Docker, sandbox
image, task set, disk) and prints the worst-case cost; nothing is spent until it passes, and the key is never printed. The
run manifest records provenance: git commit and dirtiness, hashes of the task set, the loop configurations and the runtime
requirements, interpreter and OS. `make eval` chains preflight, dry run, E1-E3 and the tables.

## What is NOT shown
No real-model result exists. The results table in `docs/evaluation_report.md` still reads "To be measured". Nothing about
PostgreSQL failover, the advisory lock, `pg_dump` scripts, Docker, Trivy or pip-audit has been exercised here.

## Known limits
- Metrics are per process and not aggregated; there is no distributed tracing and no log shipping.
- The worker metrics port has no authentication (network policy is the control).
- A worker given SIGTERM finishes its current job only if it can within `stop_grace_period`; otherwise the run is resumed
  from its checkpoint after the lease expires (this is what the chaos drill demonstrates, with `kill`).
- Backups are not encrypted by the scripts; retention does not reach into backups.
- Compose does not give the worker container access to a Docker daemon, so the real sandbox needs a host-level worker or
  your own socket/DinD arrangement.
- Two MODERATE `react-router` advisories remain (they need a breaking v7 upgrade; the exposure is low, see the review).
- Nothing was penetration-tested by a third party.
