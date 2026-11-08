#!/usr/bin/env bash
# Phase 10 exit gate = Phase 9 gate (Phases 1-9) + enterprise tests:
#   endpoint x role authorization matrix (checked complete against the app's routes), cross-organization
#   isolation, append-only audit log + completeness, quotas, retention/export/deletion, OIDC against a
#   fake identity provider, migration 0006 on real data, and the frontend (typecheck, lint, tests).
# Real identity-provider and PostgreSQL runs are not part of this gate: see ADR-0017 "Known limits".
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase9_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Phase 10: authorization matrix, isolation, audit, quotas, retention, OIDC, migration =="
(cd backend && ../$PY -m pytest tests/integration/test_phase10_authz.py \
    tests/integration/test_phase10_governance.py tests/integration/test_phase10_oidc.py \
    tests/integration/test_phase10_migration.py tests/integration/test_migrations.py -q -p no:logging)
echo
echo "== Phase 10: frontend (typecheck, lint, tests) =="
(cd frontend && npm run typecheck --silent && npm run lint --silent && npm test --silent)
echo "PHASE 10 GATE: PASS (real IdP + PostgreSQL runs: not covered here; real-model results: To be measured)"
