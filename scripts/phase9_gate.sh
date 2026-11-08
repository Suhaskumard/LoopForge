#!/usr/bin/env bash
# Phase 9 exit gate = Phase 8 gate (Phases 1-8) + smarter-loop tests:
#   failure classes, test-weakening guard, targeted Repair context, per-agent model routing,
#   similar-repair retrieval, the P0-P4 ablation presets and the ablation table.
# The harness run below uses the synthetic oracle: it proves the wiring, NOT that any feature helps.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase8_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Phase 9: failure classes, guard, targeted context, routing, retrieval =="
(cd backend && ../$PY -m pytest tests/unit/test_phase9_failure_class_and_guard.py \
    tests/agents/test_phase9_repair_and_routing.py tests/integration/test_phase9_loop.py \
    tests/integration/test_migrations.py -q -p no:logging)
echo
echo "== Phase 9: ablation table (synthetic oracle, not a measurement) =="
OUT="$(mktemp -d)"
$PY benchmarks/run_benchmarks.py --config E3,P0,P1,P2,P3,P4 --trials 2 --provider oracle \
    --tasks crud-01-employees,dv-01-isbn13 --out "$OUT" | grep -vE '^\{'
$PY benchmarks/analyze.py "$OUT" --allow-synthetic | sed -n '/Phase 9 ablations/,/not shown to help/p'
echo "PHASE 9 GATE: PASS (real-model results: To be measured - see docs/evaluation_report.md)"
