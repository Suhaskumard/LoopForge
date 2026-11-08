#!/usr/bin/env bash
# Phase 18 exit gate (release candidate) = Phase 17 gate + the platform checks:
#   the OpenAPI snapshot is current and has no breaking change against the Phase 17 baseline; rate limits, idempotency,
#   pagination and usage reports behave; the Python and TypeScript SDKs pass contract tests against the REAL server; the CLI
#   installs into a clean virtualenv; data written under the previous schema survives the upgrade (SQLite and PostgreSQL);
#   the documentation builds and every internal link and anchor resolves.
# What it does NOT do: publish anything, run an external penetration test, verify the signed-release workflow (never run), produce
# real-model evaluation results, or make this a 1.0.0 (docs/releasing.md lists what blocks that). Needs Docker AND Node >= 22.6;
# a missing tool FAILS the gate (set ALLOW_NO_NODE=1 only to skip the TypeScript SDK when you knowingly lack Node).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$([ -n "$(git status --porcelain 2>/dev/null)" ] && echo dirty || echo clean)"
echo "gate runs on commit $COMMIT ($DIRTY tree)"

docker info >/dev/null 2>&1 || { echo "FAIL: Phase 18 needs a Docker daemon (PostgreSQL upgrade test, Phase 17 drills): start Docker Desktop"; exit 1; }

bash scripts/phase17_gate.sh

echo
echo "== Phase 18: API contract (snapshot current, no breaking change) =="
"$PY" scripts/export_openapi.py --check
(cd backend && "$PY" -m pytest tests/integration/test_phase18_contract.py -q -p no:logging --no-cov)

echo
echo "== Phase 18: rate limits, idempotency, pagination, usage, plans, CLI =="
(cd backend && "$PY" -m pytest tests/integration/test_phase18_limits_and_idempotency.py \
    tests/integration/test_phase18_pagination.py tests/integration/test_phase18_usage.py \
    tests/unit/test_phase18_cli.py -q -p no:logging --no-cov)

echo
echo "== Phase 18: Python SDK against the real app =="
(cd backend && "$PY" -m pytest tests/integration/test_phase18_sdk.py -q -p no:logging --no-cov)

echo
echo "== Phase 18: TypeScript SDK against a live server =="
bash scripts/ts_sdk_contract.sh

echo
echo "== Phase 18: the CLI installs into a clean virtualenv =="
bash scripts/cli_install_check.sh

echo
echo "== Phase 18: upgrade from the previous release's schema, with data (SQLite, then PostgreSQL) =="
"$PY" scripts/upgrade_test.py
NAME="lf-upgrade-gate-$$"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$NAME" -p 127.0.0.1:5437:5432 -e POSTGRES_USER=lf -e POSTGRES_PASSWORD=lf -e POSTGRES_DB=upg postgres:16 >/dev/null
for _ in $(seq 1 60); do docker exec "$NAME" psql -U lf -d upg -tAc "select 1" >/dev/null 2>&1 && break; sleep 1; done
sleep 2
"$PY" scripts/upgrade_test.py --database-url "postgresql+psycopg://lf:lf@127.0.0.1:5437/upg"

echo
echo "== Phase 18: documentation (build + every internal link and anchor) =="
"$PY" scripts/build_docs.py
(cd backend && "$PY" -m pytest tests/integration/test_phase18_docs.py tests/integration/test_phase18_release.py \
    tests/integration/test_phase18_gate_files.py -q -p no:logging --no-cov)

echo
echo "PHASE 18 GATE: PASS on commit $COMMIT ($DIRTY tree) - release CANDIDATE only: not published, no external pen-test, signed release unverified, real-model results: To be measured"
