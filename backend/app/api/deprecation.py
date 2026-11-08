"""Deprecation signalling for the public API (Phase 18, docs/api_policy.md).

    dep = deprecated(sunset="2027-03-01", successor="/new")
    @router.get("/old", deprecated=True, dependencies=[Depends(dep)])

Adds ``Deprecation: true``, ``Sunset: <HTTP date>`` and ``Link: <successor>; rel=successor-version``
header (RFC 8594) so clients can detect it in logs and SDKs.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import format_datetime

from fastapi import Response


def deprecated(*, sunset: str, successor: str | None = None) -> Callable[[Response], None]:
    when = datetime.strptime(sunset, "%Y-%m-%d").replace(tzinfo=UTC)
    http_date = format_datetime(when, usegmt=True)

    def mark(response: Response) -> None:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = http_date
        if successor:
            response.headers["Link"] = f'<{successor}>; rel="successor-version"'

    return mark
