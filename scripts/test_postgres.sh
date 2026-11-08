#!/usr/bin/env bash
# Run the backend tests against a REAL PostgreSQL 16 (Phase 13, ADR-0020). Needs a running Docker daemon.
#   bash scripts/test_postgres.sh                 # real Alembic up/down + PostgreSQL tests + the WHOLE suite
#   PG_SUITE=quick bash scripts/test_postgres.sh  # only Alembic + the PostgreSQL-specific tests (a few minutes)
#   KEEP_DB=1 bash scripts/test_postgres.sh       # leave the container running afterwards
# A missing Docker daemon is a FAILURE, never a skip: this script exists to prove PostgreSQL works.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMPOSE=(docker compose -f docker-compose.test.yml)

docker info >/dev/null 2>&1 || { echo "FAIL: no Docker daemon is reachable (start Docker Desktop)"; exit 1; }
cleanup() { [ "${KEEP_DB:-0}" = "1" ] || "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== starting PostgreSQL 16 on localhost:5433 =="
"${COMPOSE[@]}" up -d --wait test-db
export TEST_DATABASE_URL="postgresql+psycopg://loopforge:loopforge@localhost:5433/loopforge_test"

echo
echo "== real Alembic: upgrade head, then downgrade base (fresh schema) =="
(cd backend
 export DATABASE_URL="postgresql+psycopg://loopforge:loopforge@localhost:5433/loopforge_alembic"
 docker compose -f ../docker-compose.test.yml exec -T test-db psql -U loopforge -d loopforge_test \
     -qc "DROP DATABASE IF EXISTS loopforge_alembic" -c "CREATE DATABASE loopforge_alembic"
 "$PY" -m alembic upgrade head
 "$PY" -m alembic downgrade base
 "$PY" -m alembic upgrade head)
echo "alembic up/down/up on PostgreSQL: ok"

echo
echo "== PostgreSQL-specific tests + the real backup/restore scripts =="
export PG_CONTAINER="$("${COMPOSE[@]}" ps -q test-db | head -n 1)"   # backup.sh/restore.sh run pg_dump inside it
(cd backend && "$PY" -m pytest tests/integration/test_phase13_postgres.py \
    tests/integration/test_phase13_backup_scripts.py -m postgres -q -p no:logging -p no:cacheprovider)

if [ "${PG_SUITE:-full}" = "full" ]; then
  echo
  echo "== the WHOLE backend suite on PostgreSQL (every test uses a real PostgreSQL database) =="
  (cd backend && "$PY" -m pytest -q -p no:logging -p no:cacheprovider -m "not slow and not docker and not postgres and not keycloak")
fi
echo
echo "POSTGRES TESTS: PASS"
