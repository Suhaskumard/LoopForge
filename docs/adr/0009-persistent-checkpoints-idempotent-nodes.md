# ADR-0009: Persistent checkpoints and idempotent graph nodes

**Status:** accepted (Phase 4)

**Context.** The feedback loop can run for many minutes and spend real money. A process that
dies mid-iteration must continue from where it was, without repeating paid LLM calls or
re-running completed work (spec §5.1, Phase 4 gate: "a workflow interrupted mid-iteration resumes
from its checkpoint").

**Decision.**
- `orchestrator/checkpoint.py` replaces `MemorySaver` with LangGraph's `SqliteSaver` (a sibling
  `<db>.checkpoints.sqlite` file) or `PostgresSaver` (same database as the app), chosen from the
  SQLAlchemy engine URL. State is saved after every node.
- `run_service.execute_run` records a `run_started` audit event carrying the LangGraph
  `thread_id`; `resume_run` finds it, restores the token count from the checkpoint and invokes the
  graph with `None` input so execution continues from the last completed node.
- Nodes are **idempotent**: each takes the iteration from `state["iteration"]`, looks in the
  database before redoing work (existing `test_results` row, stored review, repair marker) and
  only changes the task status when it is not already there. Re-running the node that was
  interrupted is therefore safe.
- Resume is exposed as `POST /tasks/{id}/resume` and, optionally, as a startup scan
  (`RESUME_ON_STARTUP=true`). An in-process guard prevents two runs driving one task.

**Consequences.** The per-iteration state lives in two places (checkpoint for control flow,
database for domain data); the database is authoritative and the checkpoint only says "where".
The in-process guard does not protect against two *processes* resuming the same task; a
distributed lock is future work (Phase 7). The Postgres saver is implemented but is only
exercised by the SQLite-backed test suite here.
