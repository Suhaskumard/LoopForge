#!/usr/bin/env bash
# Phase 7 exit gate = Phase 6 gate (Phases 1-6) + scale-out tests:
#   cross-process leases, job queue + worker, orphan recovery, trusted-proxy client IP
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase6_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Phase 7: scale-out tests =="
(cd backend && ../$PY -m pytest tests/integration/test_phase7_scale.py -q -p no:logging)
echo "PHASE 7 GATE: PASS"
