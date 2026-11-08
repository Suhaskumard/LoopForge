import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import ws
from app.api.errors import install_error_handlers
from app.api.v1 import (
    agents,
    analytics,
    approvals,
    auth,
    orgs,
    projects,
    publish,
    reports,
    runs,
    sso,
    tasks,
    tokens,
    webhooks,
)
from app.config import settings
from app.database import session
from app.middleware import RequestContextMiddleware
from app.utils.logging import configure_logging

configure_logging()

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth.router)
api_v1.include_router(orgs.router)
api_v1.include_router(sso.router)
api_v1.include_router(projects.router)
api_v1.include_router(tasks.router)
api_v1.include_router(runs.router)
api_v1.include_router(runs.iterations_router)
api_v1.include_router(agents.router)
api_v1.include_router(analytics.router)
api_v1.include_router(approvals.router)
api_v1.include_router(reports.router)
api_v1.include_router(publish.router)
api_v1.include_router(tokens.router)
api_v1.include_router(webhooks.router)

log = logging.getLogger("loopforge.startup")


def _resume_interrupted() -> None:
    """Continue runs that were mid-flight when the previous process died (RESUME_ON_STARTUP)."""
    from app.execution.sandbox import get_sandbox_backend
    from app.services import run_service
    from app.services.llm_client import get_llm_client

    try:
        with session.SessionLocal() as db:
            ids = run_service.interrupted_task_ids(db)
        for task_id in ids:
            log.info("resuming interrupted task %s", task_id)
            run_service.resume_run(
                session.SessionLocal, task_id, get_llm_client(), get_sandbox_backend()
            )
    except Exception:
        log.exception("resume on startup failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.resume_on_startup:
        threading.Thread(target=_resume_interrupted, daemon=True).start()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="LoopForge",
    version="0.5.0",
    description="Autonomous, feedback-driven AI software engineering platform.",
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "If-Match"],
    expose_headers=["ETag", "X-Request-ID"],
)
install_error_handlers(app)
app.include_router(api_v1)
app.include_router(ws.router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["ops"])
def ready() -> dict[str, Any]:
    """Readiness: the database is reachable."""
    try:
        with session.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from None
    return {"status": "ready"}
