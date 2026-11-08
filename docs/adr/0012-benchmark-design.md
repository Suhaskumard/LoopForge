# ADR-0012: Benchmark design - hidden tests, one loop with switches, no claim before measurement

**Status:** accepted (Phase 6)

## Context
Spec 12 treats LoopForge as an experiment: does a feedback-driven workflow beat single-shot generation, and is the
gain worth the cost? That is only answerable if (a) success is judged by something the system cannot game and (b)
the compared configurations differ in exactly one thing.

## Decision
- **30 tasks, 5 categories x 6** (CRUD, authentication, data validation, bug fixing, integration). Each has
  hidden pytest tests that no agent ever sees, a trusted reference solution, and (bug fixing) a seed. The
  requirement text is the interface specification, because the tests are hidden. `benchmarks/validate_tasks.py`
  proves each task is sound: the reference passes its hidden tests, an empty project fails them, and a broken seed
  fails them. The catalogs in `benchmarks/tools/` are the source of truth; `tasks/` is generated.
- **Independent success.** A trial succeeds only when ALL hidden tests pass, run in a separate step through the same
  sandbox after the loop ends. The loop's own verdict is recorded too, so a *false accept* (loop says COMPLETED,
  hidden tests disagree) is measurable.
- **One loop, switches.** `LoopConfig` (`orchestrator/loop_config.py`): E1 = 1 iteration, E2 = 2, E3 = production;
  A1 no Reviewer LLM, A2 no repair memory, A3 no mandatory-requirement verification, A4 no fingerprint escalation.
  Nothing is forked, so a difference can only come from the switch.
- **Same budget.** Every trial gets the same per-trial token cap; the run has hard token/cost caps and is resumable
  (`trials.jsonl`), with a `--dry-run` that prints the worst-case cost first.
- **Statistics.** Mean, sample SD and a t-interval across repetitions, plus a pooled Wilson interval (valid at 0% and
  100%). Unmeasured cells say "To be measured".
- **Synthetic runs are quarantined.** The `oracle` provider (reference solutions with injected defects) and the
  `HostSandbox` exist to test the harness without a key or Docker. Their manifest says `synthetic`, `analyze.py`
  refuses them unless asked and then stamps every table, and `HostSandbox` is wired only to the oracle.

## Consequences
- 30 tasks is a small sample: confidence intervals will be wide; the report says so.
- E4-E6 (Addendum 21.2) are not separately switchable here (traceability, failure classification and repair history
  are already part of E3), so they are reported as not implemented rather than faked.
- Bug-fixing tasks embed the broken code in the requirement text; repository-input mode arrived in Phase 8 (ADR-0015, `benchmarks/tasks_phase8/`); the original 30 tasks are unchanged.
- `regressions` is an upper-bound proxy (new failing test ids in later iterations): the system stores failures,
  not the full set of passing tests.
