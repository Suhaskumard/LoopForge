# ADR-0014: Worker service, run leases and a database job queue

**Status:** accepted (Phase 7)

**Context.** Until Phase 6 the loop ran in a FastAPI background task, so API capacity and loop
capacity were the same thing, and the only guard against two runs driving one task was an
in-process set (ADR-0009). That breaks as soon as there is more than one process.

**Decision.**
- `RUN_MODE=queue`: `start`/`resume`/approval endpoints insert a `jobs` row (idempotent per task);
  `python -m app.worker` processes claim jobs with a conditional `UPDATE ... WHERE status='queued'`
  (exactly one winner, portable to SQLite and Postgres). `inline` stays the default and unchanged.
- `run_leases`: one row per task, acquired by conditional UPDATE/INSERT, renewed by a heartbeat
  thread every `LEASE_TTL_SECONDS/3`, released on exit. This is the distributed lock deferred in
  ADR-0009; it is enforced inside `execute_run`/`resume_run`, so it also protects inline mode.
- `job_service.recover` (run periodically by every worker): a `running` job whose task has no live
  lease is failed as "worker lost", and interrupted tasks with no lease and no pending job get a
  `resume` job, continuing from the LangGraph checkpoint.
- `TRUSTED_PROXY_COUNT` makes the login rate-limit key use the real client address behind proxies.

**Consequences.**
+ Workers scale horizontally; a killed worker's task resumes elsewhere within about one lease TTL.
+ No new infrastructure (no Redis/Celery); everything is inspectable in SQL.
- Polling queue (`WORKER_POLL_SECONDS`), not push; fine at this scale.
- Clock skew between hosts shifts lease expiry; use a TTL well above expected skew.
- A worker whose lease is lost mid-run (long GC pause, DB outage) is detected by the heartbeat
  (`Heartbeat.lost`, logged) but the in-flight node is not aborted; node idempotency (ADR-0009)
  makes the takeover safe, though one node's work may be duplicated.
- Not verified on Postgres in this session; run `make test-pg`.
- WebSocket events remain DB-polled (ADR-0010); a push bus was not needed.
