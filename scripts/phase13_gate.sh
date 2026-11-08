#!/usr/bin/env bash
# Phase 13 exit gate = Phase 12 gate (Phases 1-12, which must now actually PASS) + proof on REAL infrastructure:
#   frontend audit at zero, pip-audit, the real Docker sandbox (full loop in containers), the whole backend suite on
#   PostgreSQL 16 with real Alembic and the real backup/restore scripts, OIDC against a real Keycloak, and the
#   containerised worker (socket proxy -> host daemon -> sandbox container).
# Unlike earlier gates, a check that cannot run FAILS: a missing Docker daemon or no network is a failure, not a skip.
# The gate prints the commit it ran on and whether the tree was dirty.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi

docker info >/dev/null 2>&1 || { echo "PHASE 13 GATE: FAIL - no Docker daemon (start Docker Desktop); nothing here can be skipped"; exit 1; }
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$([ -n "$(git status --porcelain 2>/dev/null)" ] && echo dirty || echo clean)"
echo "gate runs on commit $COMMIT ($DIRTY tree)"

bash scripts/phase12_gate.sh

echo
echo "== Phase 13: frontend dependencies (react-router v7): npm audit must report 0 =="
(cd frontend && npm audit --omit=dev)

echo
echo "== Phase 13: Python dependency audit (pip-audit, runtime requirements) =="
if ! "$PY" -m pip_audit --version >/dev/null 2>&1; then "$PY" -m pip install --quiet pip-audit; fi
"$PY" -m pip_audit -r backend/requirements-runtime.txt --strict

echo
echo "== Phase 13: hardening, price map, sandbox path translation, drills =="
(cd backend && "$PY" -m pytest tests/integration/test_phase13_hardening.py tests/unit/test_phase13_sandbox_paths.py \
    tests/integration/test_phase13_gate_files.py -q -p no:logging)

echo
echo "== Phase 13: the REAL Docker sandbox (full loop in containers, no network inside) =="
docker image inspect loopforge-sandbox >/dev/null 2>&1 || docker build -t loopforge-sandbox backend/sandbox
(cd backend && "$PY" -m pytest tests/execution/test_docker_real.py tests/integration/test_phase13_docker_loop.py \
    -m docker -q -p no:logging)
"$PY" scripts/acceptance_check.py | tee /tmp/acceptance13.txt | grep -E "^\s*\[(PASS|SKIP|FAIL)\]|SUMMARY"
grep -q "\[PASS\] 4\. Generated code executes in an isolated sandbox" /tmp/acceptance13.txt \
  || { echo "PHASE 13 GATE: FAIL - acceptance item 4 (real sandbox) is not PASS"; exit 1; }

echo
echo "== Phase 13: PostgreSQL 16 (real Alembic, PG-only behaviour, the whole suite, backup scripts) =="
bash scripts/test_postgres.sh

echo
echo "== Phase 13: real Keycloak (OIDC) =="
bash scripts/test_keycloak.sh

echo
echo "== Phase 13: containerised worker -> socket proxy -> host daemon -> sandbox container =="
bash scripts/docker_worker_smoke.sh

echo
echo "PHASE 13 GATE: PASS on commit $COMMIT ($DIRTY tree) - real model results: To be measured (Phase 14); GitHub CI: only after a push"
