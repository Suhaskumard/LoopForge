PY ?= .venv/Scripts/python
ifeq ($(wildcard .venv/Scripts/python),)
PY = .venv/bin/python
endif
TEST_PG ?= postgresql+psycopg://loopforge:loopforge@localhost:5432/loopforge_test

.PHONY: up down test test-pg lint fmt typecheck migrate gate

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
