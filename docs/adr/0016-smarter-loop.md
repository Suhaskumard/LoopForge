# ADR-0016: Smarter loop (Phase 9)

**Status:** accepted (Phase 9). **Claims:** none yet; see "What is NOT shown".

## Decision
Four changes to the Repair step, each behind a `LoopConfig` switch that is ON in E3 and removable for ablation:

| Switch | Preset (one off) | What it does |
|---|---|---|
| `failure_routing` | P1 | `classify_failure` (syntax > import > environment > test_wrong > logic) adds a per-class strategy to the Repair prompt; the class is stored on `repair_history`. |
| `targeted_context` | P2 | Files named in the failure report and their direct imports are sent in full, other source files as symbol outlines, non-source files as path only. If the failure names no file, everything is sent (the old behaviour). |
| `test_guard` | P3 | `detect_test_weakening` compares each edited test file before/after (Python via `ast`, JS via patterns): removed tests, fewer assertions, added skip/xfail/todo, or a file that no longer parses. A finding rejects the patch inside `repair._validator`, so the one corrective retry tells the model why. The existing "suite may not shrink" check in the Decision Engine is unchanged and remains the backstop. |
| `history_retrieval` | P4 | Repairs whose outcome was `resolved` in the same owner's *other* tasks: same fingerprint first, then same failure class (max 2), offered as hints. Other users' history is never used. |

`P0` turns all four off (Phase 8 behaviour). Per-agent model routing is configuration (`MODEL_<AGENT>`), not a switch;
`FakeLLMClient` records the requested model and `agent_runs.model` stores it. Migration `0005` adds
`agent_runs.model`, `repair_history.failure_class` and `repair_history.fingerprint` (indexed).

## Why a validator rather than a Decision Engine branch for the guard
Rejecting inside `call_agent` means a weakening patch is never written to a workspace and costs one retry, instead of
costing a full iteration and then an escalation. `decision.py` stays pure and fully covered.

## What is NOT shown
Everything above is verified for *behaviour* (unit, agent and harness tests). Whether it reduces iterations or cost is
**To be measured** with a real model: the synthetic oracle only proves the wiring. `analyze.py` prints a Phase 9 table
and labels a difference "not distinguishable from noise" when the Wilson intervals overlap.

## Known limits
- The classifier is heuristic (error type, synthetic ids, paths in the traceback); unknown cases fall back to `logic`.
- Import-following is one hop and static (`ast` / regex); dynamic imports are not followed.
- The guard counts assertions; it cannot tell a meaningful assertion from a trivial one.
- Retrieval is exact fingerprint / class match, not semantic search, and is per owner (organisation sharing: Phase 10).
- Model routing records the model, but cost estimates still use one blended `COST_PER_1K_TOKENS`; a per-model price map is not built.
