#!/usr/bin/env bash
# Phase 11 exit gate = Phase 10 gate (Phases 1-10) + integration tests:
#   pull-request delivery against a mock Git server (no write call before a recorded approval),
#   scoped API tokens, signed webhooks (signature, replay window, SSRF guard, retry), the CLI, the
#   endpoint x role matrix (still checked complete), and migration 0007.
# A live GitHub account is not part of this gate: see ADR-0018 "Known limits".
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/phase10_gate.sh
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
echo
echo "== Phase 11: publish, API tokens, webhooks, CLI, authorization matrix, migration =="
(cd backend && ../$PY -m pytest tests/integration/test_phase11_publish.py \
    tests/integration/test_phase11_tokens.py tests/integration/test_phase11_webhooks.py \
    tests/unit/test_phase11_cli.py tests/integration/test_phase10_authz.py \
    tests/integration/test_migrations.py -q -p no:logging)
echo "PHASE 11 GATE: PASS (live GitHub / real webhook receivers: not covered here)"
