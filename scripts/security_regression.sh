#!/usr/bin/env bash
# The executable security suite (Phase 17): what the team re-runs to claim a security control still holds.
# Hand this to a penetration tester so they can see what is already covered. No Docker needed.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
(cd backend && "$PY" -m pytest -q -p no:logging --no-cov \
  tests/agents/test_security_suite.py tests/integration/test_phase10_authz.py \
  tests/integration/test_phase10_governance.py tests/integration/test_phase10_oidc.py \
  tests/integration/test_phase11_webhooks.py tests/integration/test_phase13_hardening.py \
  tests/unit/test_security.py tests/unit/test_redact.py tests/unit/test_phase17_keyring.py \
  tests/unit/test_phase17_sandbox_runtime.py tests/integration/test_phase17_secrets_rotation.py \
  tests/integration/test_phase17_sso_mapping.py tests/integration/test_phase17_scim.py \
  tests/integration/test_phase17_mfa.py)
bash scripts/security_scan.sh
echo "SECURITY REGRESSION: PASS"
