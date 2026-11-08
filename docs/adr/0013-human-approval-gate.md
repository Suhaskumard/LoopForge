# ADR-0013: Human approval gate via LangGraph interrupt

**Status:** accepted (Phase 6)

## Context
Spec 13.2 lists "sensitive operations" as needing a human approval gate. The loop is autonomous and checkpointed;
a gate must pause it without losing state, survive a restart, and never be bypassable by a model.

## Decision
- Two gates only, both real: **plan review** (opt-in per task, `require_plan_approval`) and **large repair**
  (automatic when a repair touches more than `APPROVAL_MAX_REPAIR_FILES` files, default 5).
  Not built, deliberately: a *dependency* gate (unapproved packages are already hard-blocked and the sandbox has no
  network, so approving one could not make it run) and a *cost* gate (cost is a hard cap, not something to waive).
- A gate node creates an `approval_requests` row (once per task/kind/iteration), moves the task to the new status
  `AWAITING_APPROVAL`, and calls LangGraph `interrupt()`. The run returns; the checkpoint keeps the state.
- `POST /tasks/{id}/approvals/{aid}/approve` marks it approved, restores the previous status and resumes from the
  checkpoint in the background. `.../reject` escalates the task. A request can be decided once; cancelling a waiting
  task is allowed. Only the task owner can decide (foreign ids are 404).
- The node decides from the **database row**, not from the resume value, so a crash between approval and resume is
  recovered by the normal resume path; `AWAITING_APPROVAL` is excluded from startup auto-resume because it waits for
  a person, not for a process.

## Consequences
- A paused task can wait indefinitely; there is no expiry/reminder yet (Phase 10: notifications, SSO roles).
- Any owner of the task can approve; per-role approvers arrive with enterprise features.
