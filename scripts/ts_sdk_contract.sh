#!/usr/bin/env bash
# TypeScript SDK contract tests against a LIVE LoopForge server (Phase 18). No Docker needed.
# Starts the real API (SQLite, fake LLM and sandbox, per-token rate limit 3/min), type-checks the SDK with the frontend's
# pinned tsc, runs `node --test`, and stops the server. A missing node is a FAILURE unless ALLOW_NO_NODE=1.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
if ! command -v node >/dev/null 2>&1; then
  [ "${ALLOW_NO_NODE:-0}" = "1" ] && { echo "SKIP: node is not installed (ALLOW_NO_NODE=1)"; exit 0; }
  echo "FAIL: node (>= 22.6) is required for the TypeScript SDK tests"; exit 1
fi
TSC=frontend/node_modules/.bin/tsc
[ -x "$TSC" ] || { echo "FAIL: run 'npm ci' in frontend/ first (the pinned tsc lives there)"; exit 1; }

PORT="${TS_SDK_PORT:-$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')}"   # a free port, never a stale one
WORK="$(mktemp -d)"
command -v cygpath >/dev/null 2>&1 && WORK="$(cygpath -m "$WORK")"   # Windows Python needs a Windows path
cleanup() { [ -n "${API_PID:-}" ] && kill "$API_PID" >/dev/null 2>&1 || true; [ -n "${KEEP_LOG:-}" ] && cp "$WORK/api.log" "$KEEP_LOG" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

export DATABASE_URL="sqlite:///$WORK/sdk.db" WORKSPACE_ROOT="$WORK/ws" ENVIRONMENT=development
export LLM_PROVIDER=fake SANDBOX_BACKEND=fake API_TOKEN_RATE_LIMIT_PER_MINUTE=3 METRICS_ENABLED=false
(cd backend && "$PY" -m alembic upgrade head)
"$PY" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT" --log-level warning >"$WORK/api.log" 2>&1 &
API_PID=$!   # no subshell: $! must be the real server so cleanup stops it
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fs "http://127.0.0.1:$PORT/health" >/dev/null || { echo "FAIL: API did not start"; tail -20 "$WORK/api.log"; exit 1; }

echo "== type-check =="
"$TSC" -p sdk/typescript/tsconfig.json
echo "== contract tests (node $(node --version)) =="
(cd sdk/typescript && LOOPFORGE_URL="http://127.0.0.1:$PORT" npm test)
echo "TYPESCRIPT SDK: PASS"
