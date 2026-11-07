# Database schema (migration `0001`)

PostgreSQL primary store; SQLAlchemy 2.x; Alembic. Queryable fields are relational columns; JSONB only for flexible agent output (SQLite uses plain JSON in tests).

```
users 1─N projects 1─N tasks 1─N iterations 1─N agent_runs
                         │  └─N audit_events        ├─N test_results
                         │  └─N requirements        └─N artifacts
                         └─N repair_history
users 1─N refresh_tokens          login_attempts (standalone, keyed by "ip|email")
```

| Table | Notes |
|---|---|
| users | `email` unique, `password_hash` (bcrypt), `token_version` (global-logout counter) |
| projects | owner `user_id`, `language`, `version` (optimistic lock) |
| tasks | `status` CHECK-constrained to the 11 lifecycle states, `max_iterations ≥ 1`, `acceptance_criteria` JSONB, `version` |
| iterations | UNIQUE (`task_id`, `iteration_number`) |
| agent_runs · test_results · artifacts | execution evidence (spec §7.2) |
| audit_events | `task_created`, `status_changed {from,to}`, … |
| requirements | Addendum 16.1 traceability: `req_id` (UNIQUE per task), type, priority, impl/test mapping, verification_status, evidence_ref |
| repair_history | Addendum 16.2: failure, category, root cause, fix, files, tests, outcome, regression status, tokens, duration |
| refresh_tokens | SHA-256 `token_hash` (unique), `family_id`, `expires_at`, `revoked_at` |
| login_attempts | rate-limit log; index (`key`,`created_at`) |

Task lifecycle: `PENDING → PLANNING → GENERATING → EXECUTING → TESTING → REVIEWING → (REPAIRING → EXECUTING) → COMPLETED | FAILED | ESCALATED | CANCELLED`.

A test (`test_migrations.py`) fails if the models and migration ever drift, and checks the downgrade is clean.
