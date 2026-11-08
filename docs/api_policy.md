# Public API policy (Phase 18)

The contract is `docs/openapi.json` (also served at `/openapi.json`). A test fails when the running API differs from it, so every
API change is a visible diff in review. Release candidate status: this policy takes full effect at 1.0.0; until then breaking changes are
allowed but must be listed in `CHANGELOG.md` under **Changed**.

## Versioning
Semantic versions (`MAJOR.MINOR.PATCH[-rcN]`, one source: `backend/app/version.py`). The URL prefix `/api/v1` changes only with a MAJOR version.
* **PATCH** - bug fixes, no contract change.
* **MINOR** - backwards-compatible additions.
* **MAJOR** - anything breaking.

## What is breaking
Removing or renaming a path, method, request field, query parameter or enum value; making an optional input required; changing a field's type;
removing a documented success status; changing the meaning of a status code or error `code`; tightening a limit below what the docs promised.
`app/utils/openapi_compat.py` detects the mechanical cases against a baseline snapshot (`test_phase18_contract.py`); the rest is review.
**Not** breaking: new paths, methods, optional inputs, response fields or enum values - **clients must ignore unknown response fields**.

## Deprecation
1. Mark the operation `deprecated=True` and add `dependencies=[Depends(deprecated(sunset="YYYY-MM-DD", successor="/api/v1/..."))]`
   (`app/api/deprecation.py`): responses then carry `Deprecation: true`, `Sunset: <date>` and `Link: <successor>; rel="successor-version"`.
2. Announce it in `CHANGELOG.md` (**Deprecated**) and `docs/upgrade_guide.md`.
3. Keep it working for at least **two MINOR releases and 90 days**, whichever is longer; remove only in a MAJOR release.

## Authentication, limits and retries
* Credentials: a user session (JWT) or an org-bound API token (`lfk_...`, scope viewer/developer/approver). SCIM uses its own bearer token.
* **Rate limits**: API tokens default to 600 requests/minute (`API_TOKEN_RATE_LIMIT_PER_MINUTE`); sessions are unlimited unless
  `USER_RATE_LIMIT_PER_MINUTE` is set. Fixed one-minute windows, so a burst of up to 2x the limit is possible across a boundary.
  Responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (seconds); a 429 carries `Retry-After`.
* **Idempotency**: send `Idempotency-Key: <1-200 chars>` on `POST /projects`, `/tasks`, `/tasks/{id}/start`, `/tasks/{id}/publish`. Same key + same body within
  24 h returns the original response with `Idempotent-Replay: true` and does not run again; same key + different body is `422`; a retry while the first request is
  still running is `409`; failed (non-2xx) attempts are not remembered. Keys are private to the credential and organization.
* **Pagination**: collections accept `limit` (default per route, max 500, 200 for older routes) and `offset`; the body is a plain JSON array;
  `X-Total-Count` has the total and `Link: <...>; rel="next"` is present when more remain.
* **Errors**: `{"error": {"code", "message", "request_id", "details"?}}`; quote `request_id` in bug reports. SCIM uses the RFC 7644 error body.

## Stability of the SDKs
The Python and TypeScript SDKs (`sdk/`) version with the server. They are **not published** to PyPI/npm yet; install from the repository.
