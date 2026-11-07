#!/usr/bin/env bash
# Phase 1 exit gate: static checks, tests (SQLite, optionally Postgres), migration checks.
# Usage: bash scripts/phase1_gate.sh            (SQLite only)
#        WITH_PG=1 bash scripts/phase1_gate.sh  (also runs the suite on Postgres)
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ -x ../.venv/Scripts/python ]; then PY=../.venv/Scripts/python; else PY=${PYTHON:-../.venv/bin/python}; fi

echo "== ruff ==";        $PY -m ruff check . && $PY -m ruff format --check .
echo "== mypy --strict =="; $PY -m mypy app
echo "== tests (SQLite, coverage >= 95%) =="; $PY -m pytest -q --cov=app --cov-fail-under=95

if [ "${WITH_PG:-0}" = "1" ]; then
  PG=${TEST_DATABASE_URL:-postgresql+psycopg://loopforge:loopforge@localhost:5432/loopforge_test}
  echo "== tests (Postgres) =="; TEST_DATABASE_URL=$PG $PY -m pytest -q
  echo "== alembic up/down on Postgres =="
  DATABASE_URL=$PG $PY -m alembic upgrade head
  DATABASE_URL=$PG $PY -m alembic downgrade base
fi

echo
echo "Spec exit-gate evidence (tests that prove each item):"
$PY -m pytest -q \
  tests/integration/test_api.py::test_data_persists_across_restart \
  tests/integration/test_api.py::test_invalid_status_transition_rejected \
  tests/integration/test_api.py::test_cross_user_isolation
echo "PHASE 1 GATE: PASS"
