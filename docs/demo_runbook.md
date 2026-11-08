# Demonstration runbook (spec 15.2)

Task: *"Develop a FastAPI-based employee management system with authentication, CRUD endpoints, input validation and
unit tests."* The decisive moment is **a genuine failure followed by an independently verified correction**.

## A. Offline rehearsal (no API key, no Docker, 2 minutes)
A scripted model and sandbox play the story: the Builder ships an injected defect, the tests fail, the Repair agent
fixes it, the full suite re-runs, the Reviewer approves, the Decision Engine accepts, the report is written.

```bash
make ui-demo                         # terminal 1: API + WebSocket on :8000 (DEMO_DELAY=1.5 slows the steps)
cd frontend && npm install && npm run dev      # terminal 2: dashboard on :5173
```
1. Open http://localhost:5173, register any email + a password with a letter and a digit.
2. **New task** -> keep the prefilled requirement -> *Create and start* (tick *Pause for my approval after planning*
   to show the approval gate; approve it on the Live Workflow screen).
3. **Live Workflow:** watch Planner -> Builder -> Verifier light up; the timeline shows `tests_completed` with
   1 failure, `iteration_completed: failed`, Repair, `retry_scheduled`, the second test run, the Reviewer, then
   `task_completed`.
4. **Code Workspace:** choose v2, *Compare with* v1, *diff* tab -> the one-line fix in `app/routes.py`.
5. **Evaluation:** the failing test with its traceback (v1), then 5/5 passing (v2), acceptance criteria all met.
6. **Final Report:** outcome, iteration history, traceability, download the .md report and the .zip.
7. **Loop Analytics / Command Center:** KPIs; `make demo5` prints the same numbers computed straight from SQL.

When all of the above rendered correctly, record it: `ACCEPTANCE_UI_VERIFIED=1 python scripts/acceptance_check.py`.

## B. Real run (needs a key and Docker)
```bash
cp .env.example .env     # set JWT_SECRET (32+ chars), OPENAI_API_KEY, OPENAI_MODEL, LLM_PROVIDER=openai
docker build -t loopforge-sandbox backend/sandbox
docker compose up -d --build        # db + backend :8000 + dashboard :8080
python scripts/seed_database.py     # demo@example.com / demo12345
```
Open http://localhost:8080 and follow steps 2-6 above. A real model may not produce the injected defect; the
decisive moment then is whatever genuine failure it does produce - do not rehearse by editing results.

## C. Clean-environment check
`bash scripts/demo_final.sh` clones the repository to a temp directory, creates a fresh virtualenv, installs the
pinned requirements, runs the offline acceptance check and the Phase 5 evidence demo. It does not need Docker.

## Troubleshooting
- Dashboard shows `polling` instead of `live`: the WebSocket failed 3 times (proxy without upgrade headers); the
  page keeps working via REST.
- Approval banner missing: the task is not `AWAITING_APPROVAL` (check the badge); it appears only for plan-review
  tasks and for repairs touching more than `APPROVAL_MAX_REPAIR_FILES` files.
- `loop=ESCALATED`: that is a correct outcome, not a bug - read the report's *Reason*.
