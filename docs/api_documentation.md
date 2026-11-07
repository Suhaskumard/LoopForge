# API (Phase 1) — base path `/api/v1`

Interactive docs: `GET /docs` (Swagger) · `GET /openapi.json`.

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /auth/register | – | 201; 409 duplicate email; 422 weak password |
| POST | /auth/login | – | form `username`,`password` → `{access_token, refresh_token, expires_in}`; 401; 429 after 5 failures |
| POST | /auth/refresh | – | `{refresh_token}` → new pair (old one invalidated); 401 on reuse/expiry |
| POST | /auth/logout | – | `{refresh_token}` → 204, revokes that session family |
| POST | /auth/logout-all | Bearer | 204; invalidates every access + refresh token |
| GET | /auth/me | Bearer | current user |
| POST/GET | /projects | Bearer | `GET ?limit=1..200&offset=` |
| GET/PUT/DELETE | /projects/{id} | Bearer | `GET`/`PUT` return `ETag`; `PUT` honours `If-Match` (412) |
| POST/GET | /tasks | Bearer | `POST {project_id, requirement, max_iterations?, acceptance_criteria?}` |
| GET | /tasks/{id} | Bearer | returns `ETag` |
| POST | /tasks/{id}/status | Bearer | Phase-1 stand-in; invalid transition → 409; `If-Match` supported |
| GET | /tasks/{id}/events | Bearer | audit trail |
| POST | /tasks/{id}/start | Bearer | **202**; PENDING → PLANNING, then Planner→Builder run in the background. 409 unless PENDING; 412 on stale `If-Match`; 503 if the LLM provider is not configured |
| GET | /tasks/{id}/plan | Bearer | validated plan of the latest iteration (404 until planned) |
| GET | /tasks/{id}/requirements | Bearer | `REQ-###` records: type, priority, `impl_mapping`, verification status |
| GET | /tasks/{id}/agent-runs | Bearer | chronological runs: agent, status (`success|failed|timeout`), tokens, duration, error |
| GET | /tasks/{id}/files | Bearer | generated files (path, sha256) of the latest iteration |
| GET | /tasks/{id}/files/{path} | Bearer | file content; only files recorded as artifacts; confined to the workspace |
| GET | /tasks/{id}/iterations/{n}/test-results | Bearer | `test_results` rows: totals, `details.failures[]` (nodeid, message, traceback), `timed_out` |
| GET | /tasks/{id}/iterations/{n}/logs | Bearer | execution stdout/stderr stored as `log` artifacts, with sha256 |
| GET | /agents | Bearer | the six agents, which are implemented, and what each may not do |
| GET | /health · /health/ready | – | liveness · DB readiness (503 if down) |

Errors: `{"error":{"code","message","request_id","details?"}}`. Codes: `bad_request unauthorized forbidden not_found conflict precondition_failed validation_error rate_limited unavailable internal_error`. Every response carries `X-Request-ID`.

Example:
```bash
curl -X POST :8000/api/v1/auth/register -H 'content-type: application/json' -d '{"email":"a@b.co","password":"password123"}'
curl -X POST :8000/api/v1/auth/login -d 'username=a@b.co&password=password123'
```
