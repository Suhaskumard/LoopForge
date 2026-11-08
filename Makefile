PY ?= .venv/Scripts/python
ifeq ($(wildcard .venv/Scripts/python),)
PY = .venv/bin/python
endif
TEST_PG ?= postgresql+psycopg://loopforge:loopforge@localhost:5432/loopforge_test

.PHONY: up down test test-pg lint fmt typecheck migrate gate gate2 demo2 gate3 demo3 sandbox-image gate4 demo4 gate5 demo5 ui-demo gate6 gate7 gate8 bench-validate bench-harness acceptance demo-final

up:        ## start Postgres + backend
	docker compose up -d --build

down:
	docker compose down

lint:
	cd backend && ../$(PY) -m ruff check . && ../$(PY) -m ruff format --check .

fmt:
	cd backend && ../$(PY) -m ruff format . && ../$(PY) -m ruff check . --fix

typecheck:
	cd backend && ../$(PY) -m mypy app

test:      ## SQLite suite with coverage floor
	cd backend && ../$(PY) -m pytest -q --cov=app --cov-fail-under=95

test-pg:   ## same suite on Postgres (needs `docker compose up -d db`)
	cd backend && TEST_DATABASE_URL=$(TEST_PG) ../$(PY) -m pytest -q

migrate:
	cd backend && ../$(PY) -m alembic upgrade head

gate:      ## Phase 1 exit gate, one command
	bash scripts/phase1_gate.sh

gate2:     ## Phase 1 + Phase 2 gates and the evidence demo
	bash scripts/phase2_gate.sh

demo2:     ## print Phase 2 exit-gate evidence (no API key needed)
	$(PY) scripts/demo_phase2.py

gate3:     ## Phase 1-3 gates and the sandbox evidence demo
	bash scripts/phase3_gate.sh

demo3:     ## print Phase 3 exit-gate evidence (real-container checks need Docker)
	$(PY) scripts/demo_phase3.py

sandbox-image:  ## build the sandbox image used for generated-code execution
	docker build -t loopforge-sandbox backend/sandbox

gate4:     ## Phase 1-4 gates, Decision Engine coverage and the feedback-loop demo (Milestone 1)
	bash scripts/phase4_gate.sh

demo4:     ## print Phase 4 exit-gate evidence (no API key or Docker needed)
	$(PY) scripts/demo_phase4.py

gate5:     ## Phase 1-5 gates, frontend checks and the KPI-vs-database demo
	bash scripts/phase5_gate.sh

demo5:     ## print Phase 5 exit-gate evidence (no API key, Docker or browser needed)
	$(PY) scripts/demo_phase5.py

ui-demo:   ## API with a scripted loop on :8000 - run `npm run dev` in frontend/ for the dashboard
	$(PY) scripts/dev_demo_server.py

gate6:     ## everything above + 30 benchmark tasks + acceptance checklist + harness check
	bash scripts/phase6_gate.sh

gate7:     ## everything above + scale-out tests (leases, queue/worker, trusted proxy)
	bash scripts/phase7_gate.sh

gate8:     ## everything above + repository input, JS profile, 20 new benchmark tasks
	bash scripts/phase8_gate.sh

bench-validate:  ## prove all 30 benchmark tasks are sound
	$(PY) benchmarks/validate_tasks.py

bench-harness:   ## synthetic harness check (NOT a measurement); real runs: see docs/evaluation_report.md
	$(PY) benchmarks/run_benchmarks.py --config E1,E3 --trials 2 --provider oracle --tasks crud-01-employees,dv-01-isbn13 --out /tmp/lf_harness

acceptance:      ## spec 15.1 checklist with evidence
	$(PY) scripts/acceptance_check.py

demo-final:      ## clean-environment rehearsal (fresh venv from pinned requirements)
	bash scripts/demo_final.sh
