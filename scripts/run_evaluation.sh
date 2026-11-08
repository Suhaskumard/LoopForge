#!/usr/bin/env bash
# The REAL evaluation (Phase 12): preflight -> cost ceiling -> E1/E2/E3 -> optional ablations -> tables.
# Needs OPENAI_API_KEY, OPENAI_MODEL, COST_PER_1K_TOKENS, a running Docker daemon and the sandbox image.
# Nothing is spent unless the preflight passes. Re-running resumes (results are appended to trials.jsonl).
#
#   MAX_TOTAL_COST=25 TRIALS=3 bash scripts/run_evaluation.sh            # E1-E3
#   MAX_TOTAL_COST=60 WITH_ABLATIONS=1 bash scripts/run_evaluation.sh    # + A1-A4 and P0-P4
#
# Every figure that ends up in docs/results_*.md comes from the trials.jsonl written here, with a manifest that
# records the commit, task set, loop configurations and requirements that produced it.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
TRIALS="${TRIALS:-3}"
OUT="${OUT:-benchmarks/results}"
: "${MAX_TOTAL_COST:?set MAX_TOTAL_COST (USD) so the run cannot spend more than you intend}"

echo "== 1. preflight (nothing is spent) =="
$PY benchmarks/preflight.py --config E1,E2,E3 --trials "$TRIALS" --max-total-cost "$MAX_TOTAL_COST" --out "$OUT/e1-e3"

echo
echo "== 2. dry run: the plan and the worst-case cost =="
$PY benchmarks/run_benchmarks.py --config E1,E2,E3 --trials "$TRIALS" --provider openai --dry-run --out "$OUT/e1-e3"

echo
echo "== 3. E1 / E2 / E3 (real model, Docker sandbox) =="
$PY benchmarks/run_benchmarks.py --config E1,E2,E3 --trials "$TRIALS" --provider openai \
    --out "$OUT/e1-e3" --max-total-cost "$MAX_TOTAL_COST"
$PY benchmarks/analyze.py "$OUT/e1-e3" --out docs/results_e1_e3.md
echo "wrote docs/results_e1_e3.md"

if [ "${WITH_ABLATIONS:-0}" = "1" ]; then
  echo
  echo "== 4. ablations A1-A4 and the Phase 9 switches P0-P4 =="
  $PY benchmarks/run_benchmarks.py --config E3,A1,A2,A3,A4,P0,P1,P2,P3,P4 --trials "$TRIALS" --provider openai \
      --out "$OUT/ablations" --max-total-cost "$MAX_TOTAL_COST"
  $PY benchmarks/analyze.py "$OUT/ablations" --out docs/results_ablations.md
  echo "wrote docs/results_ablations.md"
fi
echo
echo "DONE. Read docs/results_*.md, then update docs/evaluation_report.md with the real numbers and the failure analysis."
