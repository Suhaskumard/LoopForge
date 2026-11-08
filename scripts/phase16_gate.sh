#!/usr/bin/env bash
# Phase 16 exit gate = Phase 15 gate + the "smarter, broader loop" checks:
#   the new switches are off by default and each has an ablation preset, the new mechanisms behave
#   (patch conflicts, affected-tests-first, partial results, verification extras, memory opt-out/expiry),
#   the Go adapter parses and is policy-safe, the Go tasks are well formed, held-out tasks are protected.
# What it does NOT do: show that any switch helps (nothing is measured on a real model), compile the
# Go tasks without a Go toolchain (validate_go.py says so loudly), or build the Go sandbox image.
# Set REQUIRE_GO=1 where Go is installed to make the behavioural Go checks mandatory.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$([ -n "$(git status --porcelain 2>/dev/null)" ] && echo dirty || echo clean)"
echo "gate runs on commit $COMMIT ($DIRTY tree)"

bash scripts/phase15_gate.sh

echo
echo "== Phase 16: mechanisms, Go adapter, gate files =="
(cd backend && "$PY" -m pytest tests/integration/test_phase16_loop.py tests/unit/test_phase16_go.py \
    tests/integration/test_phase16_gate_files.py tests/integration/test_migrations.py -q -p no:logging)

echo
echo "== Phase 16: Go tasks =="
if [ "${REQUIRE_GO:-0}" = "1" ]; then "$PY" benchmarks/validate_go.py --require-go; else "$PY" benchmarks/validate_go.py; fi

echo
echo "== Phase 16: defaults (new switches off) and held-out protection =="
"$PY" benchmarks/check_defaults.py
"$PY" benchmarks/run_benchmarks.py --suite full --heldout --provider oracle --dry-run

echo
echo "PHASE 16 GATE: PASS on commit $COMMIT ($DIRTY tree) - real-model improvement: NOT claimed (To be measured)"
