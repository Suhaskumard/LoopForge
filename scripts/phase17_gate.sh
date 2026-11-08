#!/usr/bin/env bash
# Phase 17 exit gate = Phase 16 gate + the "trust at scale" checks:
#   key ring and rotation, webhook secret rotation, SSO group mapping, SCIM, TOTP MFA, sandbox runtime
#   (fail closed), queue back-pressure, SLO/alert and compliance-mapping consistency, migration 0012,
#   the security regression suite, and (Docker required) a measured DR drill and a PostgreSQL load profile.
# What it does NOT do: run an external penetration test, measure gVisor/Kata, verify the signed-release
# workflow (it has never run on GitHub), or show production capacity. A missing Docker daemon FAILS the gate.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$([ -n "$(git status --porcelain 2>/dev/null)" ] && echo dirty || echo clean)"
echo "gate runs on commit $COMMIT ($DIRTY tree)"

docker info >/dev/null 2>&1 || { echo "FAIL: Phase 17 needs a Docker daemon (DR drill, PostgreSQL load): start Docker Desktop"; exit 1; }

bash scripts/phase16_gate.sh

echo
echo "== Phase 17: security regression suite =="
bash scripts/security_regression.sh

echo
echo "== Phase 17: back-pressure, compliance docs, gate files, migrations =="
(cd backend && "$PY" -m pytest tests/integration/test_phase17_backpressure.py \
    tests/integration/test_phase17_compliance_docs.py tests/integration/test_phase17_gate_files.py \
    tests/integration/test_migrations.py -q -p no:logging)

echo
echo "== Phase 17: disaster-recovery drill (measures RTO / RPO on real PostgreSQL) =="
"$PY" scripts/dr_drill.py --max-rto 300 --max-rpo 30 --out docs/dr_drill_result.json

echo
echo "== Phase 17: PostgreSQL load profile against the SLO =="
LOAD_OUT=docs/load_postgres_result.json bash scripts/load_postgres.sh

echo
echo "PHASE 17 GATE: PASS on commit $COMMIT ($DIRTY tree) - external pen-test, gVisor measurement, signed release: NOT done"
