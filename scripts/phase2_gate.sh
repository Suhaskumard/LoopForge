#!/usr/bin/env bash
# Phase 2 exit gate = everything in Phase 1's gate (lint, mypy, full suite, migrations, optional
# Postgres) PLUS the Phase 2 evidence demo (plan+IDs, workspace-only files, rejected output, injection).
# Usage: bash scripts/phase2_gate.sh           (SQLite)
#        WITH_PG=1 TEST_DATABASE_URL=... bash scripts/phase2_gate.sh
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase1_gate.sh
echo
echo "== Phase 2 evidence demo =="
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
$PY scripts/demo_phase2.py | grep -vE '^\{'
echo "PHASE 2 GATE: PASS"
