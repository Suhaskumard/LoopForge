#!/usr/bin/env bash
# Phase 8 exit gate = Phase 7 gate (Phases 1-7) + existing-repository / language tests:
#   language profiles, hardened repo import, repo-input task fixed end to end offline,
#   JavaScript flow, and the 20 new benchmark tasks (10 repo-input, 10 JavaScript).
# JavaScript benchmark tasks need Jest: set LOOPFORGE_JEST to jest's bin/jest.js. Without it they are
# reported SKIP (never PASS).
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase7_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Phase 8: language profiles, repository import, repo-input flow =="
(cd backend && ../$PY -m pytest tests/unit/test_phase8_languages_and_import.py tests/integration/test_phase8_repo_flow.py -q -p no:logging)
echo
echo "== Phase 8: benchmark tasks (repo-input + JavaScript) =="
$PY benchmarks/validate_phase8.py
echo "PHASE 8 GATE: PASS (JS tasks marked SKIP above were not validated; real-model results: To be measured)"
