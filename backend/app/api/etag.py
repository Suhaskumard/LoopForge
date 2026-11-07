"""Optimistic concurrency helpers: ETag from the row version, If-Match precondition."""

from fastapi import HTTPException, Response, status


def etag_for(version: int) -> str:
    return f'"{version}"'


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = etag_for(version)


def check_if_match(if_match: str | None, version: int) -> None:
    """If the client sent If-Match it must equal the current ETag (or be `*`)."""
    if if_match is None or if_match.strip() == "*":
        return
    candidates = {c.strip().removeprefix("W/") for c in if_match.split(",")}
    if etag_for(version) not in candidates:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, "ETag mismatch: stale resource")
