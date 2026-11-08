"""Errors raised by the LoopForge SDK. Every non-2xx answer becomes an ``APIError`` subclass."""

from __future__ import annotations

from typing import Any


class LoopForgeError(Exception):
    """Base class for everything this SDK raises."""


class TransportError(LoopForgeError):
    """The server could not be reached (after retries)."""


class APIError(LoopForgeError):
    def __init__(
        self,
        status: int,
        message: str,
        *,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status, self.message, self.code = status, message, code
        self.request_id, self.body, self.retry_after = request_id, body, retry_after


class BadRequest(APIError): ...


class Unauthorized(APIError): ...


class Forbidden(APIError): ...


class NotFound(APIError): ...


class Conflict(APIError): ...


class ValidationError(APIError): ...


class RateLimited(APIError): ...


class ServerError(APIError): ...


_BY_STATUS: dict[int, type[APIError]] = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    422: ValidationError,
    429: RateLimited,
}


def error_for(status: int) -> type[APIError]:
    if status in _BY_STATUS:
        return _BY_STATUS[status]
    return ServerError if status >= 500 else APIError
