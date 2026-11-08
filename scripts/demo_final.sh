#!/usr/bin/env bash
# Clean-environment rehearsal (spec 11.6 exit gate 3): copy the working tree WITHOUT .venv, node_modules,
# .git or generated workspaces into a temp dir, create a fresh virtualenv from the pinned requirements, then
# run the offline acceptance check and the Phase 5 evidence demo there. Needs network for pip; no Docker/key.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "== copying a clean tree to $TMP =="
(cd "$SRC" && tar --exclude=.venv --exclude=node_modules --exclude=.git --exclude=workspaces \
    --exclude=__pycache__ --exclude=dist --exclude='*.db' --exclude=.env -cf - .) | tar -xf - -C "$TMP"
cd "$TMP"
PYBIN="${PYTHON:-python}"
echo "== fresh virtualenv + pinned dependencies =="
"$PYBIN" -m venv .venv
if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=.venv/bin/python; fi
$PY -m pip install -q --disable-pip-version-check -r backend/requirements.txt
echo "== acceptance checklist (spec 15.1) =="
$PY scripts/acceptance_check.py | grep -vE '^\{'
echo "== evidence demo (live events, diff, KPIs == SQL) =="
$PY scripts/demo_phase5.py | grep -vE '^\{'
echo "== benchmark tasks: validate three, harness-run two (synthetic) =="
$PY benchmarks/validate_tasks.py --tasks crud-01-employees,bug-01-pagination,int-01-inventory-orders
$PY benchmarks/run_benchmarks.py --config E1,E3 --trials 1 --provider oracle \
    --tasks crud-01-employees,dv-01-isbn13 --out "$TMP/bench_out" | grep -vE '^\{'
echo "CLEAN-ENVIRONMENT DEMO: PASS"
