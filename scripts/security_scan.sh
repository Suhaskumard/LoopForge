#!/usr/bin/env bash
# Local security scan (Phase 12, ADR-0019): static analysis + dependency audits.
#   bandit        REQUIRED  medium+ findings fail this script (low findings are listed in docs/security_review.md)
#   pip-audit     when installed and the network is reachable (CI always runs it)
#   npm audit     when npm and the network are reachable   (CI always runs it)
# A skipped audit is reported as SKIP and is never counted as a pass. REQUIRE_AUDITS=1 turns a skip into a failure.
set -uo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=${PYTHON:-.venv/bin/python}; fi
status=0; skipped=0

echo "== bandit (backend/app, medium and above) =="
if (cd backend && ../$PY -m bandit -r app -ll -q 2>/dev/null); then
  echo "  [PASS] no medium or high findings"
else
  echo "  [FAIL] bandit reported medium/high findings (run: cd backend && python -m bandit -r app -ll)"; status=1
fi

echo "== pip-audit (runtime requirements) =="
if $PY -m pip_audit --version >/dev/null 2>&1; then
  if $PY -m pip_audit -r backend/requirements-runtime.txt --strict >/tmp/pip_audit.out 2>&1; then
    echo "  [PASS] no known vulnerabilities"
  else
    echo "  [FAIL]"; tail -n 20 /tmp/pip_audit.out; status=1
  fi
else
  echo "  [SKIP] pip-audit is not installed (pip install pip-audit); CI runs it"; skipped=$((skipped+1))
fi

echo "== npm audit (frontend production dependencies, high and above) =="
if command -v npm >/dev/null 2>&1 && [ -d frontend/node_modules ]; then
  if (cd frontend && npm audit --omit=dev --audit-level=high >/tmp/npm_audit.out 2>&1); then
    echo "  [PASS] no high/critical advisories"
  elif grep -qiE "ENOTFOUND|EAI_AGAIN|network|ETIMEDOUT" /tmp/npm_audit.out; then
    echo "  [SKIP] the advisory service is unreachable (offline)"; skipped=$((skipped+1))
  else
    echo "  [FAIL]"; tail -n 20 /tmp/npm_audit.out; status=1
  fi
else
  echo "  [SKIP] npm or frontend/node_modules missing"; skipped=$((skipped+1))
fi

echo
if [ "$status" -ne 0 ]; then echo "SECURITY SCAN: FAIL"; exit 1; fi
if [ "$skipped" -gt 0 ] && [ "${REQUIRE_AUDITS:-0}" = "1" ]; then
  echo "SECURITY SCAN: FAIL ($skipped audit(s) skipped and REQUIRE_AUDITS=1)"; exit 1
fi
echo "SECURITY SCAN: PASS ($skipped audit(s) skipped, not counted as passed)"
