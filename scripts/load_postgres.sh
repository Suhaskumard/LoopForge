#!/usr/bin/env bash
# Load profile on REAL PostgreSQL (Phase 17): API + queue mode against a throwaway PostgreSQL 16, checked
# against the SLO targets in docs/slo.md. The numbers are what THIS machine produced (one container, one API
# process, fake LLM + fake sandbox): a floor for regression detection, not a capacity claim for production.
#
#   bash scripts/load_postgres.sh                      # defaults: 20 users x 3 tasks x 15 reads
#   USERS=40 SLO_P95=1.0 bash scripts/load_postgres.sh
# Needs a running Docker daemon (a missing one is a FAILURE, not a skip).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
docker info >/dev/null 2>&1 || { echo "FAIL: no Docker daemon is reachable (start Docker Desktop)"; exit 1; }

NAME="lf-load-$$"; PORT="${LOAD_PG_PORT:-5438}"; API_PORT="${LOAD_API_PORT:-8077}"
USERS="${USERS:-20}"; SLO_P95="${SLO_P95:-2.5}"; SLO_ERR="${SLO_ERR:-0.005}"
cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" >/dev/null 2>&1 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "$NAME" -p "127.0.0.1:$PORT:5432" -e POSTGRES_USER=loopforge -e POSTGRES_PASSWORD=loopforge \
    -e POSTGRES_DB=loopforge_load postgres:16 -c max_connections=200 >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" psql -U loopforge -d loopforge_load -tAc "select 1" >/dev/null 2>&1 && break; sleep 1
done
export DATABASE_URL="postgresql+psycopg://loopforge:loopforge@127.0.0.1:$PORT/loopforge_load"
export ENVIRONMENT=development LLM_PROVIDER=fake SANDBOX_BACKEND=fake RUN_MODE=queue METRICS_ENABLED=false
(cd backend && "$PY" -m alembic upgrade head)
(cd backend && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --log-level warning >"${LOAD_API_LOG:-/dev/null}" 2>&1) &
API_PID=$!
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$API_PORT/health/ready" >/dev/null 2>&1 && break; sleep 1; done
curl -fs "http://127.0.0.1:$API_PORT/health/ready" >/dev/null || { echo "FAIL: API did not become ready"; exit 1; }

"$PY" scripts/load_test.py --url "http://127.0.0.1:$API_PORT" --users "$USERS" --tasks 3 --reads 15 \
    --slo-p95 "$SLO_P95" --slo-error-rate "$SLO_ERR" ${LOAD_OUT:+--out "$LOAD_OUT"}
