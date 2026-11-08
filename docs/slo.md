# Service level objectives (Phase 17)

These are **targets with an error budget**, not measurements of production. LoopForge has never served production traffic, so nothing
here is a claim about observed reliability. What *is* measured is listed under "Evidence so far", with the machine and the limits.

## Objectives

| # | Objective | Target | Error budget (30 days) | Indicator (metric) |
|---|---|---|---|---|
| S1 | **API availability** | 99.5 % of requests do not fail with 5xx | 0.5 % of requests (~3 h 36 min if all traffic failed) | `loopforge_http_requests_total{status_class="5xx"}` / all |
| S2 | **API latency** | 99 % of requests complete in under 2.5 s | 1 % of requests | `loopforge_http_request_duration_seconds_bucket{le="2.5"}` |
| S3 | **Run start** | A started task is claimed by a worker within 5 min, 99 % of the time | 1 % of time with a queue older than 5 min | `loopforge_jobs_oldest_queued_age_seconds` (alert `LoopForgeQueueBacklog`) |
| S4 | **Durability** | After losing the database host, service is restored with **RTO <= 15 min** and **RPO <= the backup interval** | n/a (a drill result, not a rate) | `scripts/dr_drill.py` |

What the objectives deliberately exclude: the correctness of what the agents produce (that is the evaluation, `docs/evaluation_report.md`),
the model provider's availability (visible as `loopforge_llm_calls_total{outcome="failed"}`, alerted separately) and long-running task
duration (a task legitimately takes minutes).

## How the alerts follow from the budget

`deploy/observability/alerts.yml`, group `loopforge-slo`, uses the multi-window multi-burn-rate pattern. Burn rate = (observed bad ratio) /
(budget ratio); at burn rate *B* the whole 30-day budget is spent in 30/*B* days.

| Alert | Burn rate | Windows | Bad ratio threshold (S1) | Meaning | Severity |
|---|---|---|---|---|---|
| `LoopForgeAvailabilityBudgetFastBurn` | 14.4 | 1 h and 5 m | 7.2 % | budget gone in ~2 days | page |
| `LoopForgeAvailabilityBudgetSlowBurn` | 6 | 6 h and 30 m | 3 % | budget gone in ~5 days | page |
| `LoopForgeAvailabilityBudgetTicket` | 1 | 3 d and 6 h | 0.5 % | on course to use the whole budget | warn |
| `LoopForgeLatencyBudgetFastBurn` | 14.4 | 1 h and 5 m | 14.4 % slower than 2.5 s | S2 | warn |
| `LoopForgeQueueBackpressure` | - | 10 m | any refusal | starts are being refused (see back-pressure) | warn |

The long window shows the burn is significant, the short window shows it is still happening, so an alert resolves quickly once fixed.
A test (`test_phase17_slo_docs.py`) keeps this table, the alert file and the metric names consistent.

## Capacity controls

* **Back-pressure** - `MAX_QUEUED_JOBS` (global) and `MAX_QUEUED_JOBS_PER_ORG` refuse `POST /tasks/{id}/start` with **429 + `Retry-After`**
  while the queue is full. The task stays `PENDING` and can be started again. Both default to 0 (unlimited). Each refusal is audited
  (`queue.backpressure`) and counted (`loopforge_backpressure_total{scope}`).
* **Autoscaling** - KEDA scales workers on queue depth (`deploy/observability/keda-worker-scaledobject.yaml`); never exercised on a real cluster.
* **Quotas** - per-organization and per-member token/task caps already bound a single tenant's spend (Phases 10 and 15).

## Evidence so far (all from one development machine)

| What | Result | Source | Read it as |
|---|---|---|---|
| Load on PostgreSQL 16 (20 virtual users, 780 requests, fake LLM and sandbox, one API process, queue mode) | p50 0.15 s, **p95 0.49 s**, max 1.77 s, **0 server errors**, 0 cross-tenant leaks, 91 requests/s | `docs/load_postgres_result.json`, `scripts/load_postgres.sh` | Within S1/S2 on this machine for this mix. A floor for regression detection, **not** a capacity claim: no real LLM, no real sandbox work, no network, one process. |
| Disaster recovery (database container killed with `docker kill`, replacement provisioned, `restore.sh`, migrations, readiness) | **RTO 15.4 s**, **RPO 3.4 s** (backup taken 3 s before the failure), 0 invented rows, audit append-only triggers intact | `docs/dr_drill_result.json`, `scripts/dr_drill.py` | Proves the procedure and the scripts. RTO grows with database size; **RPO equals your backup interval** - a nightly backup means up to a day of loss. |

## Not yet known (To be measured)

* Behaviour under real model latency, real sandbox contention and multiple workers on a cluster.
* The right alert thresholds: the burn-rate windows follow the formulas, but they have not been tuned on real traffic.
* RTO for a database of realistic size, and a managed-database failover (Phase 12's note on failover stands).
* Whether 99.5 % / 99 % are the *right* targets for users - they are a starting position to be revised after the first months of data.

## Reviewing the SLOs

Review monthly: budget spent per objective, the incidents that spent it, and whether a target should tighten or relax. Re-run
`scripts/dr_drill.py` after any change to backups, the schema size class, or the database platform, and quarterly regardless.
