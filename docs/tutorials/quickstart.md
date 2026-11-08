# Quickstart

Goal: run LoopForge on your machine with the scripted (no API key) demo model, sign in, and watch a task complete. Takes about ten minutes.
Needs Python 3.12 and Node 22; Docker only if you want the real sandbox.

## 1. Backend
```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt        # Windows: .venv\Scripts\pip
cp .env.example .env                                                              # defaults are fine for development
cd backend && ../.venv/bin/python -m alembic upgrade head
../.venv/bin/python -m uvicorn app.main:app --port 8000
```
Check it is up: `curl localhost:8000/health` returns `{"status":"ok","version":"1.0.0-rc1"}`.

## 2. The scripted demo (no key, no Docker)
`make ui-demo` starts the API with a scripted model and sandbox on port 8000 and seeds a demo account; then in another terminal:
```bash
cd frontend && npm install && npm run dev      # http://localhost:5173
```
Development builds sign you in automatically; otherwise register an account. Create a project, add a task such as *"Build an employee management API with tests"*, press **Start**,
and watch the iterations, test results and the final report appear.

## 3. With a real model
Set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL` (and `COST_PER_1K_TOKENS` or `MODEL_PRICES_JSON`) and build the sandbox image (`docker build -t loopforge-sandbox backend/sandbox`,
`SANDBOX_BACKEND=docker`). Start with a small `token_budget` per task. Real-model quality has **not** been measured yet: see the [evaluation report](../evaluation_report.md).

## 4. From the command line
```bash
pip install ./backend                       # provides the `loopforge` command
export LOOPFORGE_URL=http://localhost:8000 LOOPFORGE_TOKEN=lfk_...     # create a token under Admin -> API tokens
loopforge run --repo https://github.com/org/repo --requirement "add a /health endpoint" --wait
loopforge completion bash > /etc/bash_completion.d/loopforge
```

## Next
[Use the API and SDKs](api_and_sdks.md), [operate it](operating.md), or read the [architecture](../architecture.md).
