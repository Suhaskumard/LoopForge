"""Idempotency-Key handling for the create endpoints automation retries (Phase 18).

One middleware instead of four copies in the routes. It only acts on ``POST`` requests that carry an
``Idempotency-Key`` header and match ``IDEMPOTENT_ROUTES``. See services/idempotency_service.py
for the
semantics. The scope of a key is a hash of the caller's credential (API token, or the JWT's subject)
and the ``X-Org-Id`` header, so keys cannot be shared or probed across callers. A replay is served
without re-running authentication: it can only return a response this same credential already
received.
"""

import re

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.database.session import get_session_factory
from app.services import idempotency_service as idem
from app.services.api_token_service import is_api_token
from app.utils.security import decode_access_token

HEADER = "idempotency-key"
IDEMPOTENT_ROUTES = (
    re.compile(r"^/api/v1/projects$"),
    re.compile(r"^/api/v1/tasks$"),
    re.compile(r"^/api/v1/tasks/[^/]+/start$"),
    re.compile(r"^/api/v1/tasks/[^/]+/publish$"),
)
KEPT_HEADERS = ("etag", "content-type")


def _credential(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    if is_api_token(token):
        return "api:" + token
    claims = decode_access_token(token)
    return None if claims is None else "user:" + str(claims["sub"])


def _error(status: int, message: str) -> Response:
    return JSONResponse(
        {"error": {"code": "idempotency", "message": message, "request_id": None}},
        status_code=status,
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = request.headers.get(HEADER)
        path = request.url.path
        if (
            request.method != "POST"
            or key is None
            or not any(r.match(path) for r in IDEMPOTENT_ROUTES)
        ):
            return await call_next(request)
        if not key.strip() or len(key) > idem.KEY_MAX_LENGTH:
            return _error(422, f"Idempotency-Key must be 1-{idem.KEY_MAX_LENGTH} characters")
        credential = _credential(request)
        if credential is None:  # unauthenticated: let the normal 401 happen, store nothing
            return await call_next(request)

        body = await request.body()
        route = "POST " + re.sub(r"/[0-9a-fA-F-]{36}(?=/|$)", "/{id}", path)
        scope = idem.scope_of(credential, request.headers.get("x-org-id"))
        req_hash = idem.request_hash(request.method, path, body)
        factory = request.app.dependency_overrides.get(get_session_factory, get_session_factory)()
        with factory() as db:
            started = idem.begin(db, scope, key, route, req_hash)
        if started.outcome == "mismatch":
            return _error(422, "this Idempotency-Key was already used with a different request")
        if started.outcome == "in_progress":
            return _error(409, "a request with this Idempotency-Key is still being processed")
        if started.outcome == "replay":
            headers = {k: v for k, v in (started.headers or {}).items() if k != "content-type"}
            return Response(
                started.body,
                status_code=started.status_code,
                media_type=(started.headers or {}).get("content-type", "application/json"),
                headers={**headers, "Idempotent-Replay": "true"},
            )

        assert started.record_id is not None  # nosec B101 - "run" always carries the record id
        try:
            response = await call_next(request)
            payload = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
        except BaseException:
            with factory() as db:
                idem.forget(db, started.record_id)
            raise
        stored = 200 <= response.status_code < 300 and len(payload) <= idem.MAX_STORED_BODY
        with factory() as db:
            if stored:
                kept = {k: v for k, v in response.headers.items() if k in KEPT_HEADERS}
                idem.complete(
                    db, started.record_id, response.status_code, payload.decode("utf-8"), kept
                )
            else:  # failures are not remembered: the retry runs for real
                idem.forget(db, started.record_id)
        out = Response(payload, status_code=response.status_code, media_type=response.media_type)
        out.raw_headers = list(response.raw_headers)
        return out


__all__ = ["IdempotencyMiddleware", "settings"]
