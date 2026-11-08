#!/usr/bin/env bash
# Regression benchmark (Phase 14). KIND=oracle (default, free, no key or Docker) or KIND=real (budgeted; needs a key,
# Docker and MAX_TOTAL_COST). The subset, thresholds and the real baseline live in benchmarks/regression/subset.json.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
KIND="${KIND:-oracle}"
OUT="${OUT:-${TMPDIR:-/tmp}/lf_regression_$KIND}"
TASKS="$($PY -c "import json;print(','.join(json.load(open('benchmarks/regression/subset.json'))['tasks']))")"
CONFIGS="$($PY -c "import json;print(','.join(json.load(open('benchmarks/regression/subset.json'))['configs']))")"
TRIALS="$($PY -c "import json;print(json.load(open('benchmarks/regression/subset.json'))['trials'])")"
rm -rf "$OUT"
if [ "$KIND" = "real" ]; then
  : "${MAX_TOTAL_COST:?set MAX_TOTAL_COST (USD) for the nightly regression run}"
  $PY benchmarks/run_benchmarks.py --provider openai --config "$CONFIGS" --trials "$TRIALS" --tasks "$TASKS" \
      --out "$OUT" --max-total-cost "$MAX_TOTAL_COST"
else
  $PY benchmarks/run_benchmarks.py --provider oracle --config "$CONFIGS" --trials "$TRIALS" --tasks "$TASKS" --out "$OUT"
fi
$PY benchmarks/regression.py "$OUT" --kind "$KIND"
