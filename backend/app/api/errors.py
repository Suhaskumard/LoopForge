"""Uniform error envelope: {"error": {"code", "message", "request_id", "details"?}}."""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.logging import request_id_var

log = logging.getLogger("loopforge.errors")

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    412: "precondition_failed",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def _envelope(
    status_code: int,
    message: str,
    headers: dict[str, str] | None = None,
    details: object = None,
) -> JSONResponse:
    error: dict[str, object] = {
        "code": _CODES.get(status_code, "error" if status_code < 500 else "internal_error"),
        "message": message,
        "request_id": request_id_var.get(),
    }
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status_code, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    from app.services.scim_service import ScimError

    @app.exception_handler(ScimError)
    async def _scim(_: Request, exc: ScimError) -> JSONResponse:
        # SCIM clients expect the RFC 7644 error body, not the LoopForge envelope
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(
            exc.body(), status_code=exc.status, media_type="application/scim+json", headers=headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = getattr(exc, "headers", None)
        return _envelope(exc.status_code, str(exc.detail), headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return _envelope(422, "Request validation failed", details=details)

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError) -> JSONResponse:
        return _envelope(409, "The resource was modified concurrently; reload and retry")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return _envelope(500, "Internal server error")


__all__ = ["HTTPException", "install_error_handlers"]
