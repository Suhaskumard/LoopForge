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
| GET | /health · /health/ready | – | liveness · DB readiness (503 if down) |

Errors: `{"error":{"code","message","request_id","details?"}}`. Codes: `bad_request unauthorized forbidden not_found conflict precondition_failed validation_error rate_limited unavailable internal_error`. Every response carries `X-Request-ID`.

Example:
```bash
curl -X POST :8000/api/v1/auth/register -H 'content-type: application/json' -d '{"email":"a@b.co","password":"password123"}'
curl -X POST :8000/api/v1/auth/login -d 'username=a@b.co&password=password123'
```
