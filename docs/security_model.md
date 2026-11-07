# LoopForge — Security Model (Phase 1 scope)

| Threat | Control | Where / proof |
|---|---|---|
| Credential stuffing / brute force | Failed logins logged in `login_attempts` (DB-backed, shared across workers); 5 failures per (IP,email) per 5 min → 429 + `Retry-After`; success clears the counter | `services/auth_service.py`, `test_auth_sessions.py`, `test_hardening.py` |
| Weak passwords | ≥8 chars, letter + digit; bcrypt hashing | `schemas/user.py`, `utils/security.py` |
| Stolen access token | 15-min lifetime; `tv` claim must equal `users.token_version` → `logout-all` kills all live access tokens instantly | `api/dependencies.py` |
| Stolen refresh token | Opaque 384-bit random; only SHA-256 stored; **rotation on every use**; replay of a spent token revokes the whole family | `services/auth_service.rotate`, `test_refresh_token_reuse_revokes_whole_family` |
| Forged / expired JWT | HS256 signature + `exp` verified; unknown subject rejected | `test_expired_and_foreign_tokens_rejected` |
| Weak production secret | App refuses to start with `JWT_SECRET` = default or <32 chars when `ENVIRONMENT=production` | `config.py` |
| Cross-tenant data access | All queries owner-scoped; foreign IDs return **404** (not 403) to avoid existence leaks | `test_cross_user_isolation` |
| Lost updates / races | `version_id_col`, `If-Match`/ETag, row lock on status transitions | `test_concurrency.py` |
| Invalid state in DB | CHECK constraints (status values, iterations ≥1), UNIQUE (task, iteration#), UNIQUE (task, req_id) | `models.py`, `test_hardening.py` |
| Info leaks via errors | Unhandled exceptions return a generic 500 + request id; details only in server logs | `api/errors.py` |
| Clickjacking / sniffing / caching | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` | `middleware.py` |
| Container compromise blast radius | Multi-stage image, non-root UID 10001, HEALTHCHECK | `backend/Dockerfile` |

## Known limits (honest list)
- Rate-limit key uses the direct client IP; behind a proxy configure trusted `X-Forwarded-For` handling (Phase 7/10).
- HS256 shared secret; asymmetric keys / rotation arrive with SSO (Phase 10).
- No email verification or password reset yet.
- Generated-code sandboxing is Phase 3 and is **not** covered here.
