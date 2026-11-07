# ADR-0005: SQLite for the fast test loop, Postgres for truth
Status: accepted. Decision: default pytest run uses file SQLite (fast, no Docker); CI and 'make test-pg' run the identical suite on Postgres. Row locks (FOR UPDATE) are no-ops on SQLite, so concurrency guarantees are verified on Postgres. A migration-drift test guards schema parity.
