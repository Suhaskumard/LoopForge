import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.logging import request_id_var
from app.utils.metrics import HTTP_DURATION, HTTP_REQUESTS

log = logging.getLogger("loopforge.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, emit an access log line, add basic security headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed = time.perf_counter() - start
            ms = elapsed * 1000
            # the route *template* keeps label cardinality bounded (never raw paths or ids)
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            HTTP_REQUESTS.inc(
                method=request.method, route=route, status_class=f"{response.status_code // 100}xx"
            )
            HTTP_DURATION.observe(elapsed, route=route)
            # logged while the id is still set: the access line must carry this request's id
            log.info(
                "%s %s -> %s (%.1fms)", request.method, request.url.path, response.status_code, ms
            )
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response
