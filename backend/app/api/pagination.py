"""One pagination contract for every collection endpoint (Phase 18, docs/api_policy.md).

    page: Pager = Depends(pager())          # ?limit=&offset=, defaults to the route's choice
    return page.slice(rows)

The response keeps its plain JSON-array body (so existing clients are unaffected) and carries the
paging facts in headers: ``X-Total-Count`` and, when more remain, ``Link: <...>; rel="next"``.
Collections that are bounded by design (a task's iterations, the agent catalogue, templates) are
listed in ``test_phase18_platform.BOUNDED`` with the reason, so a new unbounded list cannot slip in.
"""

from collections.abc import Callable, Sequence
from typing import TypeVar
from urllib.parse import urlencode

from fastapi import Query, Request, Response

T = TypeVar("T")


class Pager:
    def __init__(self, request: Request, response: Response, limit: int, offset: int) -> None:
        self.request, self.response, self.limit, self.offset = request, response, limit, offset

    def slice(self, items: Sequence[T]) -> list[T]:
        total = len(items)
        self.response.headers["X-Total-Count"] = str(total)
        if self.offset + self.limit < total:
            query = dict(self.request.query_params)
            query.update(limit=str(self.limit), offset=str(self.offset + self.limit))
            url = f"{self.request.url.path}?{urlencode(query)}"
            self.response.headers["Link"] = f'<{url}>; rel="next"'
        return list(items[self.offset : self.offset + self.limit])


def pager(default: int = 200, maximum: int = 500) -> Callable[..., Pager]:
    def dependency(
        request: Request,
        response: Response,
        limit: int = Query(default, ge=1, le=maximum, description="Page size"),
        offset: int = Query(0, ge=0, description="Items to skip"),
    ) -> Pager:
        return Pager(request, response, limit, offset)

    return dependency
