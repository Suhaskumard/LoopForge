# ADR-0021: Measurement tooling for the real evaluation (Phase 14)

**Status:** accepted (Phase 14, tooling only). **Principle:** never publish a number that was not measured. This phase builds
everything the real-model evaluation needs and the checks that keep its report honest. It does **not** run a real model: no API key or
budget was available, so every result is still "To be measured".

## What was built
| Piece | What it does |
|---|---|
| Phase 8 suite in the runner | `--suite core\|phase8\|all`. The 10 repo-input tasks are seeded through the same zip import users get; the 10 JavaScript tasks run in a JavaScript project and are scored with Jest (`parse_jest_report`). The default stays the 30 core tasks. The synthetic oracle refuses Phase 8 tasks. |
| Per-agent cost | The runner priced every trial at one blended rate. It now sums each agent run at its own model's rate (`cost_of_runs`), so routing and `MODEL_PRICES_JSON` show up in cost per solved task. |
| Manifest | Adds `tasks_phase8_sha256` and `settings_sha256` (models, routing, price map, iteration and token defaults) next to the existing commit, task, loop-config and requirements hashes. |
| Noise verdicts | `analyze.paired_difference` / `switch_verdict`: per-task success-rate differences against E3 with a 95% t-interval over tasks. An interval containing 0 reads "not distinguishable from noise (NOT shown to help)". |
| Failure analysis | Failure rate and most common failure class by category, tasks solved in under half their trials, and the false-accept count. Why they fail is written by a human from the transcripts. |
| `check_report.py` | The report's results block is regenerated from `docs/evaluation/trials.jsonl` and compared exactly. With no published run the block must say "To be measured" and hold no figures. Synthetic runs and runs missing E1/E2/E3 are refused. |
| `check_defaults.py` | A `decisions` comment in the report (iterations, token budget, routing, switches on/off) is compared with the `Settings` and `LoopConfig` defaults. Empty means no decision yet. |
| Regression benchmark | `benchmarks/regression/subset.json` (6 fixed tasks, E1 and E3). CI runs it against the oracle (E3 success floor, E3 over E1 gap, zero false accepts). `nightly-eval.yml` runs it against the real model when a key, model and cap are configured. |
| Gate 14 | `scripts/phase14_gate.sh` = gate 13 + task validation + the tests above + regression + both checks. It prints the commit and says real results are "To be measured" when none are published. |

## Decisions
- **Paired by task.** Task difficulty varies far more than a switch's effect, so differences are taken per task and the interval is over
  tasks, not trials. With the 30-task suite the intervals will still be wide; "not distinguishable" is the expected answer for small effects.
- **The report is generated, not typed.** The only way for a number to appear in the results block is `check_report.py --write`, and
  the gate fails if the block and `trials.jsonl` disagree.
- **No invented baselines.** The real regression baseline is `null` until a measured run fills it in. A null baseline records results
  and prints a notice; it cannot alert.
- **Acting on evidence is a checked step, not a promise.** After the real run, switches that are not distinguishable from noise are
  turned off in `LoopConfig` (or removed) and recorded in the `decisions` block; `check_defaults.py` fails if the code disagrees.

## Known limits
- **Nothing here is measured.** No E1-E3 or ablation result, no cost per solved task, no failure analysis exists yet. The Phase 14 goal
  (does the loop beat single-shot, and is it worth the cost) is open until `make eval` is run with a key, a model and a budget.
- The Phase 8 JavaScript and repo-input paths of the runner are exercised by unit tests and a dry run, not by a real model or the Docker
  sandbox in this phase.
- The regression subset is six tasks; its real-model threshold needs a measured baseline and has a 15 point tolerance, which is wide on purpose.
- The oracle regression catches pipeline breakage, not model quality.
- The cost per solved task is still `tokens x configured rate`, not a bill.
- Re-deriving routing and the token/iteration defaults, and removing switches, cannot happen without results; that follows the real run and
  feeds Phase 16.
