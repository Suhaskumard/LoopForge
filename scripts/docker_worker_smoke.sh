#!/usr/bin/env bash
# End-to-end smoke test of the containerised worker with the REAL sandbox (Phase 13, ADR-0020). Needs Docker.
#
#   API (queue mode) -> job -> worker CONTAINER -> docker-socket-proxy -> host Docker daemon -> sandbox container
#
# The model is the built-in fake; everything else is real: the worker runs in its own container, asks the host
# daemon (through the proxy) to start the locked-down sandbox, bind-mounting the host path that
# SANDBOX_HOST_WORKSPACE_ROOT translates the worker's /data/workspaces to. The task must COMPLETE with tests that
# really ran. A failure at any step is a FAILURE of this script.
#
#   bash scripts/docker_worker_smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker info >/dev/null 2>&1 || { echo "FAIL: no Docker daemon is reachable (start Docker Desktop)"; exit 1; }
docker image inspect loopforge-sandbox >/dev/null 2>&1 || { echo "FAIL: build the sandbox image first: docker build -t loopforge-sandbox backend/sandbox"; exit 1; }
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi

export COMPOSE_PROJECT_NAME=loopforge-smoke
export BACKEND_PORT="${BACKEND_PORT:-8011}"
export DB_PORT="${DB_PORT:-55432}"   # keep clear of any PostgreSQL already on 5432
export LF_HOST_WORKSPACES="${LF_HOST_WORKSPACES:-$PWD/.smoke/workspaces}"
export SANDBOX_HOST_WORKSPACE_ROOT="$LF_HOST_WORKSPACES"
mkdir -p "$LF_HOST_WORKSPACES"
ENVFILE="$PWD/.smoke/smoke.env"
cat > "$ENVFILE" <<EOF
ENVIRONMENT=development
JWT_SECRET=smoke-test-secret-smoke-test-secret-1234
LLM_PROVIDER=fake
SANDBOX_BACKEND=docker
RUN_MODE=queue
DOCUMENTATION_AGENT_ENABLED=false
LEASE_TTL_SECONDS=20
WORKER_POLL_SECONDS=0.5
SANDBOX_HOST_WORKSPACE_ROOT=$SANDBOX_HOST_WORKSPACE_ROOT
EOF
COMPOSE=(docker compose --env-file "$ENVFILE" -f docker-compose.yml -f docker-compose.worker-docker.yml -f docker-compose.smoke.yml --profile workers-docker)
cleanup() { "${COMPOSE[@]}" logs --no-color worker-docker > .smoke/worker.log 2>&1 || true; "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== building images and starting db, migrate, backend, socket proxy, worker-docker =="
"${COMPOSE[@]}" up -d --build --wait db docker-proxy backend worker-docker
URL="http://localhost:$BACKEND_PORT"

echo "== driving one task through the API =="
"$PY" - "$URL" <<'PYEOF'
import json, sys, time, urllib.parse, urllib.request

base = sys.argv[1] + "/api/v1"

def call(method, path, body=None, form=None, token=None):
    data, headers = None, {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read() or b"null")

call("POST", "/auth/register", {"email": "smoke@example.com", "password": "smoketest123"})
token = call("POST", "/auth/login", form={"username": "smoke@example.com", "password": "smoketest123"})[1]["access_token"]
project = call("POST", "/projects", {"name": "smoke"}, token=token)[1]
task = call("POST", "/tasks", {"project_id": project["id"], "requirement": "Build a small employee API with tests please."}, token=token)[1]
status, _ = call("POST", f"/tasks/{task['id']}/start", token=token)
assert status == 202, status
deadline = time.time() + 240
while time.time() < deadline:
    state = call("GET", f"/tasks/{task['id']}", token=token)[1]["status"]
    if state in ("COMPLETED", "FAILED", "ESCALATED", "CANCELLED"):
        break
    time.sleep(2)
iterations = call("GET", f"/tasks/{task['id']}/iterations", token=token)[1]
print("final status:", state, "| iterations:", [(i["number"], i["status"], i["tests"]) for i in iterations])
assert state == "COMPLETED", f"the task ended {state}"
tests = iterations[-1]["tests"]
assert tests["total_tests"] > 0 and tests["failed"] == 0, tests   # real pytest ran in a real sandbox container
print("SMOKE: tests really ran inside the sandbox:", tests)
PYEOF

echo "== evidence from the worker container's log =="
"${COMPOSE[@]}" logs --no-color worker-docker 2>&1 | grep -E "claimed by|finished: done" | head -n 4 || true
echo
echo "DOCKER WORKER SMOKE: PASS (worker container -> socket proxy -> host daemon -> sandbox container)"
