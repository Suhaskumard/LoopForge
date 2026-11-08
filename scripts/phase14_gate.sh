#!/usr/bin/env bash
# Phase 14 exit gate = Phase 13 gate + the measurement tooling:
#   Phase 8 suite loadable by the runner, per-model cost in the runner, paired noise verdicts and failure analysis,
#   the regression benchmark against the oracle, report-vs-trials and defaults-vs-decisions checks.
# What it does NOT do: run a real model. Real results are published only after `make eval`; until then the
# report must say "To be measured" and the checks enforce that. The gate prints the commit and dirty flag.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$([ -n "$(git status --porcelain 2>/dev/null)" ] && echo dirty || echo clean)"
echo "gate runs on commit $COMMIT ($DIRTY tree)"

bash scripts/phase13_gate.sh

echo
echo "== Phase 14: task sets are sound =="
"$PY" benchmarks/validate_tasks.py
"$PY" benchmarks/validate_phase8.py

echo
echo "== Phase 14: measurement tooling tests =="
(cd backend && "$PY" -m pytest tests/unit/test_phase14_measurement.py tests/integration/test_phase14_gate_files.py \
    tests/unit/test_benchmark_analysis.py tests/integration/test_benchmark_harness.py -q -p no:logging)

echo
echo "== Phase 14: regression benchmark (synthetic oracle) =="
PYTHON="$PY" bash scripts/bench_regression.sh

echo
echo "== Phase 14: report matches trials, defaults match decisions =="
"$PY" benchmarks/check_report.py
"$PY" benchmarks/check_defaults.py

echo
if [ -f docs/evaluation/trials.jsonl ]; then RESULT="published (see docs/evaluation_report.md)"; else RESULT="To be measured (run make eval, publish into docs/evaluation/)"; fi
echo "PHASE 14 GATE: PASS on commit $COMMIT ($DIRTY tree) - real model results: $RESULT"
