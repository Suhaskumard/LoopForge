#!/usr/bin/env bash
# Phase 4 exit gate (Milestone 1) = Phase 3 gate (which includes Phases 1-2)
#   + Decision Engine 100% branch coverage
#   + the feedback-loop evidence demo (all five gate items).
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase3_gate.sh
echo
echo "== Decision Engine branch coverage (must be 100%) =="
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
(cd backend && ../$PY -m pytest -q tests/unit/test_decision.py tests/unit/test_decision_cost.py \
  --cov=app.orchestrator.decision --cov-branch --cov-fail-under=100 2>&1 | grep -E "decision.py|TOTAL|passed|failed|Required")
echo
echo "== Phase 4 evidence demo =="
$PY scripts/demo_phase4.py | grep -vE '^\{'
echo "PHASE 4 GATE: PASS"
