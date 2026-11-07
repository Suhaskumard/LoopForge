#!/usr/bin/env bash
# One-time local setup: venv, deps, .env, database, migrations.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m venv .venv
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=.venv/bin/python; fi
$PY -m pip install -r backend/requirements.txt
[ -f .env ] || cp .env.example .env
docker compose up -d db
(cd backend && ../$PY -m alembic upgrade head)
echo "Ready. Run: cd backend && ../$PY -m uvicorn app.main:app --reload"
