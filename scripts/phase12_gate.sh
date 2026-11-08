#!/usr/bin/env bash
# Phase 12 exit gate = Phase 11 gate (Phases 1-11) + operations tests and drills:
#   observability (ids, metrics, alerts consistent with the registry), reliability (migration lock, compose/Docker
#   structure, runtime-only dependencies), a REAL crash-recovery drill (kill a worker process, another finishes the
#   task), a backup/restore drill, a live-server load + isolation smoke, bandit (medium+ fails), the real-evaluation
#   kit (preflight blockers, provenance) and a security-scan summary.
# Not covered (stated, not hidden): real model results, PostgreSQL paths, Docker/Trivy/pip-audit, a pen-test.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase11_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Phase 12: observability, reliability, security, evaluation kit, drills (incl. slow tests) =="
(cd backend && ../$PY -m pytest tests/integration/test_phase12_observability.py \
    tests/integration/test_phase12_reliability.py tests/integration/test_phase12_security.py \
    tests/integration/test_phase12_evaluation_kit.py tests/integration/test_phase12_drills.py \
    tests/integration/test_migrations.py -m "slow or not slow" -q -p no:logging)
echo
echo "== Phase 12: crash-recovery drill (real worker killed mid-task) =="
$PY scripts/chaos_drill.py
echo
echo "== Phase 12: backup and restore drill =="
$PY scripts/backup_drill.py
echo
echo "== Phase 12: security scan =="
bash scripts/security_scan.sh
echo
echo "== Phase 12: evaluation preflight (harness view; a real run needs a key, Docker and a cap) =="
$PY benchmarks/preflight.py --provider oracle
echo "PHASE 12 GATE: PASS (real-model results: To be measured; PostgreSQL, Docker, CI scanners and pen-test: not covered here)"
