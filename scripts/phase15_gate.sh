#!/usr/bin/env bash
# Phase 15 exit gate = Phase 14 gate + the product-experience checks:
#   email verification / reset / invitations / sessions / notifications / member quotas (backend tests),
#   frontend lint + typecheck + unit tests + build, and the Playwright suite in a real browser
#   (journeys, axe accessibility with no serious/critical violations, phone width).
# What it does NOT do: deliver real email to a real provider (the Mailpit/SMTP test runs only when
# SMTP_TEST_HOST is set, as in CI), test other browsers than Chromium, or replace a manual accessibility audit.
# Set SKIP_E2E=1 to skip the browser suite on a machine without Playwright browsers (the gate then says so).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$([ -n "$(git status --porcelain 2>/dev/null)" ] && echo dirty || echo clean)"
echo "gate runs on commit $COMMIT ($DIRTY tree)"

bash scripts/phase14_gate.sh

echo
echo "== Phase 15: accounts, invitations, notifications, quotas (backend) =="
(cd backend && "$PY" -m pytest tests/integration/test_phase15_accounts.py tests/integration/test_phase15_smtp.py \
    tests/integration/test_phase15_gate_files.py tests/integration/test_phase10_authz.py \
    tests/integration/test_migrations.py -q -p no:logging)

echo
echo "== Phase 15: frontend lint, types, unit tests, build =="
(cd frontend && npm ci --no-audit --no-fund && npm run lint && npm run typecheck && npm test && npm run build)

echo
if [ "${SKIP_E2E:-0}" = "1" ]; then
  E2E="SKIPPED (SKIP_E2E=1)"
else
  echo "== Phase 15: Playwright (desktop + phone width, axe) =="
  (cd frontend && npx playwright install chromium && CI=true PYTHON="$PY" npx playwright test)
  E2E="passed"
fi

echo
echo "PHASE 15 GATE: PASS on commit $COMMIT ($DIRTY tree) - browser suite: $E2E"
