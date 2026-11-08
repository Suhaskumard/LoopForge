"""`GET /metrics`: Prometheus text exposition (Phase 12, ADR-0019).

Off unless `METRICS_ENABLED=true` (a disabled endpoint is a plain 404, indistinguishable from no
route). When `METRICS_TOKEN` is set the caller must send it as a bearer token. Metrics hold no
user data or ids, but they do show activity levels, so do not expose the endpoint publicly
without the token or a network policy.
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database.session import get_db
from app.services import ops_metrics
from app.utils.metrics import REGISTRY

router = APIRouter(tags=["ops"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def authorize_metrics(authorization: str | None) -> None:
    if not settings.metrics_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if settings.metrics_token:
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(supplied, settings.metrics_token):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "metrics token required",
                headers={"WWW-Authenticate": "Bearer"},
            )  # fmt: skip


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> PlainTextResponse:
    authorize_metrics(authorization)
    ops_metrics.refresh_db_gauges(db)
    return PlainTextResponse(REGISTRY.render(), media_type=CONTENT_TYPE)
