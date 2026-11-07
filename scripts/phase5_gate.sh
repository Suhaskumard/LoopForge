#!/usr/bin/env bash
# Phase 5 exit gate = Phase 4 gate (which includes Phases 1-3)
#   + frontend: typecheck, lint, unit tests, production build
#   + the evidence demo (live events, diff between iterations, KPIs == SQL).
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase4_gate.sh
echo
echo "== Frontend =="
(cd frontend && npm ci --no-audit --no-fund --silent && npm run typecheck && npm run lint && npm test && npm run build >/dev/null && echo "frontend build ok")
echo
echo "== Phase 5 evidence demo =="
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
$PY scripts/demo_phase5.py | grep -vE '^\{'
echo "PHASE 5 GATE: PASS"
