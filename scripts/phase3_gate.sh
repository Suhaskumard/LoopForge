#!/usr/bin/env bash
# Phase 3 exit gate = Phase 2 gate (which includes Phase 1) PLUS the sandbox evidence demo.
# Real-container checks run when Docker and the image exist
# (docker build -t loopforge-sandbox backend/sandbox); otherwise they are reported as SKIPPED
# and tests marked `docker` are skipped.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase2_gate.sh
echo
echo "== Phase 3 evidence demo =="
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
$PY scripts/demo_phase3.py | grep -vE '^\{'
echo "PHASE 3 GATE: PASS"
