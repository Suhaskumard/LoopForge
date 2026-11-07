# ADR-0003: PostgreSQL + JSONB, SQLAlchemy 2.x, Alembic
Status: accepted. Decision: relational columns for anything queried or aggregated (KPIs must equal DB computations), JSONB only for flexible agent output. Tests run on SQLite via a JSON/JSONB variant and the same suite runs on Postgres in CI (TEST_DATABASE_URL).
