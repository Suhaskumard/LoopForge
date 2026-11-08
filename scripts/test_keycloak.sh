#!/usr/bin/env bash
# Run the OIDC tests against a REAL Keycloak (Phase 13, ADR-0020). Needs a running Docker daemon.
#   bash scripts/test_keycloak.sh
#   KEEP_KC=1 bash scripts/test_keycloak.sh     # leave Keycloak running afterwards (http://localhost:8180)
# A missing Docker daemon is a FAILURE, never a skip. First start pulls the Keycloak image (~450 MB).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMPOSE=(docker compose -f docker-compose.test.yml --profile oidc)

docker info >/dev/null 2>&1 || { echo "FAIL: no Docker daemon is reachable (start Docker Desktop)"; exit 1; }
cleanup() { [ "${KEEP_KC:-0}" = "1" ] || "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== starting Keycloak (realm 'loopforge' is imported on start) =="
"${COMPOSE[@]}" up -d --wait keycloak
export KEYCLOAK_URL="http://localhost:8180"
echo
echo "== OIDC tests against the real provider =="
(cd backend && "$PY" -m pytest tests/integration/test_phase13_oidc_keycloak.py -m keycloak -q -p no:logging -p no:cacheprovider)
echo
echo "KEYCLOAK OIDC TESTS: PASS"
