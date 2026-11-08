# LoopForge - Evaluation report

> **Status: no experiment has been run.** The benchmark, runner and statistics are built and validated, but the
> comparison needs a real model (an OpenAI key) and the Docker sandbox, neither of which was available when this
> was written. Per spec 12.5 and Addendum 21.3, **no figure below is a result.** Everything marked
> "To be measured" stays that way until `benchmarks/run_benchmarks.py` has produced it.

## Research question (spec 12)
Does a feedback-driven multi-agent workflow improve task completion and code quality over single-shot AI code
generation, and does the gain justify the extra latency and cost?

## What was built and verified
| Piece | State | Evidence |
|---|---|---|
| 30 tasks, 5 categories x 6, hidden tests, references, seeds | built | `python benchmarks/validate_tasks.py` -> `30 tasks ... ALL TASKS VALID` |
| Task soundness: reference passes, empty project fails, broken seed fails | verified for all 30 | same command |
| Runner with E1-E3 and A1-A4 switches, repeated trials, resume, token/cost caps, dry-run | built, harness-tested | `backend/tests/integration/test_benchmark_harness.py` |
| Independent hidden-test scoring (separate step, same sandbox) | built, tested | same |
| Statistics: mean, SD, t-interval, Wilson interval, TSR/TPR/IE/RR/CPS/false-accept | built, checked against hand-computed values | `backend/tests/unit/test_benchmark_analysis.py` |
| Real-model runs | **not run** | needs `OPENAI_API_KEY`, `OPENAI_MODEL`, Docker image |

The only runs executed were **harness checks** with the synthetic `oracle` model (reference solutions with injected
defects). They prove the pipeline, e.g. that E1 cannot repair, E3 can, a hopeless defect makes E3 escalate early, and
a loop-accepted/hidden-rejected result is counted as a false accept. They say nothing about LoopForge's quality.

## How to produce the results
```bash
# 1. build the sandbox image once (Docker running)
docker build -t loopforge-sandbox backend/sandbox
# 2. see the worst-case cost BEFORE spending anything
export OPENAI_API_KEY=... OPENAI_MODEL=... COST_PER_1K_TOKENS=<your blended price>
python benchmarks/run_benchmarks.py --config E1,E2,E3 --trials 3 --provider openai --dry-run
# 3. run it (resumable; stops at the caps; results in trials.jsonl)
python benchmarks/run_benchmarks.py --config E1,E2,E3 --trials 3 --provider openai \
    --out benchmarks/results/e1-e3 --max-total-cost 25
# 4. ablations
python benchmarks/run_benchmarks.py --config A1,A2,A3,A4 --trials 3 --provider openai --out benchmarks/results/ablations
# 5. tables
python benchmarks/analyze.py benchmarks/results/e1-e3 --out docs/results_e1_e3.md
```
Use >= 3 trials per task so the spread is meaningful. Use the same model, token budget and sandbox for every
configuration (the runner enforces the last two).

## Results template (spec 12.5) - to be filled by `analyze.py`
| Metric | E1 | E2 | E3 |
|---|---|---|---|
| Task success rate | To be measured | To be measured | To be measured |
| Test pass rate (hidden) | To be measured | To be measured | To be measured |
| Average iterations | 1 (by construction) | To be measured | To be measured |
| Regression proxy | To be measured | To be measured | To be measured |
| Cost per success | To be measured | To be measured | To be measured |

| Ablation | Removed | Question | Result |
|---|---|---|---|
| A1 | Independent Reviewer | Does independent review improve quality? | To be measured |
| A2 | Repair memory | Does retained failure context reduce repeated mistakes? | To be measured |
| A3 | Requirement verification | Does explicit checking reduce incomplete implementations? | To be measured |
| A4 | Adaptive retry | Does selective retry improve efficiency? | To be measured |

E4-E6 and RQ4/RQ5 (risk-aware verification, mutation testing; Addendum 21-22) are not implemented, so they cannot
be measured; RQ1-RQ3 are only partly addressable because traceability, failure classification and regression
analysis are part of E3 and cannot be switched off independently.

## Threats to validity (state these alongside any result)
- 30 tasks; confidence intervals will be wide. A different task mix could change conclusions.
- Tasks are small, single-service FastAPI projects authored by the same team that built the system.
- LLM output is stochastic and a provider may change a model silently; record the model name and date (the manifest does).
- Hidden tests encode our reading of each requirement; an ambiguous requirement penalises every configuration equally but is still noise.
- Cost is `tokens x configured rate`, not a bill.
- The regression metric is a proxy (new failing test ids in later iterations), not the spec's exact definition.
