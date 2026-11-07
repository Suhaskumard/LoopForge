# ADR-0010: WebSocket events derived from the database, not an in-process bus

**Status:** accepted (Phase 5)

## Context
The dashboard must show every agent step live (spec §8.2). The loop runs in a FastAPI background task; the
socket handler may run in a different worker. An in-process pub/sub would silently lose events across workers
and on restart, and a late subscriber would see nothing.

## Decision
`/ws/tasks/{id}` polls the rows the loop already writes (`audit_events`, `agent_runs`, `iterations`) every
`WS_POLL_SECONDS` and emits events it has not sent yet. `services/event_stream.py::build_events` is a pure
function from rows to the spec event vocabulary. Event ids are stable (`audit:<id>`, `run-start:<id>`, ...), so
history is replayed on connect, reconnects never duplicate, and the REST fallback in the UI produces the same ids.
A terminal event is ordered after its own run's verdict, because the Decision Engine changes status a few
milliseconds before it records the verdict.

## Consequences
+ Correct with many workers, after restarts, and for late joiners; no new infrastructure; trivially testable.
- About 1 s latency and one small query per open socket per second. Per-user connection cap bounds the cost.
  A push bus (Postgres LISTEN/NOTIFY or Redis) belongs to Phase 7 when scale demands it.
Auth: browsers cannot set headers on a WebSocket, so the access JWT is a `token` query parameter with the same
checks as REST (signature, expiry, `tv`). Tokens are short-lived (15 min); log lines must not record the query string.
