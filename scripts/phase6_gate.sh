#!/usr/bin/env bash
# Phase 6 exit gate = Phase 5 gate (Phases 1-5)
#   + all 30 benchmark tasks proven sound (reference passes, empty/seed fails)
#   + spec 15.1 acceptance checklist (PASS/SKIP/FAIL with evidence; SKIP is reported, never counted as PASS)
#   + benchmark harness check with the synthetic oracle (NOT a measurement)
# Real E1-E3 results need an API key: see docs/evaluation_report.md.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase5_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Benchmark tasks (30, hidden tests) =="
$PY benchmarks/validate_tasks.py
echo
echo "== Acceptance checklist (spec 15.1) =="
$PY scripts/acceptance_check.py | grep -vE '^\{'
echo
echo "== Benchmark harness check (synthetic oracle, not a measurement) =="
OUT="$(mktemp -d)"
$PY benchmarks/run_benchmarks.py --config E1,E2,E3 --trials 2 --provider oracle \
    --tasks crud-01-employees,auth-01-jwt-basic,dv-01-isbn13,bug-01-pagination,int-01-inventory-orders --out "$OUT" | grep -vE '^\{'
$PY benchmarks/analyze.py "$OUT" --allow-synthetic | head -22
echo "PHASE 6 GATE: PASS (real-model results: To be measured - see docs/evaluation_report.md)"
