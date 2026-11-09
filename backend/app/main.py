import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import metrics, ws
from app.api.errors import install_error_handlers
from app.api.v1 import (
    advanced,
    agents,
    analytics,
    approvals,
    auth,
    graph,
    guide,
    intel,
    mfa,
    notifications,
    orgs,
    projects,
    publish,
    reports,
    runs,
    scim,
    sso,
    tasks,
    tokens,
    webhooks,
)
from app.config import settings
from app.database import session
from app.idempotency_middleware import IdempotencyMiddleware
from app.middleware import RequestContextMiddleware
from app.utils.logging import configure_logging, thread_target
from app.version import __version__

configure_logging()

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth.router)
api_v1.include_router(mfa.router)
api_v1.include_router(orgs.router)
api_v1.include_router(orgs.invites_router)
api_v1.include_router(notifications.router)
api_v1.include_router(guide.router)
api_v1.include_router(sso.router)
api_v1.include_router(projects.router)
api_v1.include_router(tasks.router)
api_v1.include_router(runs.router)
api_v1.include_router(runs.iterations_router)
api_v1.include_router(agents.router)
api_v1.include_router(analytics.router)
api_v1.include_router(graph.router)
api_v1.include_router(intel.router)
api_v1.include_router(advanced.router)
api_v1.include_router(approvals.router)
api_v1.include_router(reports.router)
api_v1.include_router(publish.router)
api_v1.include_router(tokens.router)
api_v1.include_router(webhooks.router)
api_v1.include_router(scim.router)
api_v1.include_router(scim.admin_router)

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


def _inline_starter() -> Any:
    from app.execution.sandbox import get_sandbox_backend
    from app.services import intel_service, run_service
    from app.services.llm_client import get_llm_client

    def start(task_id: Any) -> None:
        run_service.dispatch(
            intel_service.ThreadBackground(), session.SessionLocal, "start", task_id,
            get_llm_client(), get_sandbox_backend(),
        )  # fmt: skip

    return start


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.services.intel_service import RegressionScheduler

    if settings.resume_on_startup:
        threading.Thread(target=thread_target(_resume_interrupted), daemon=True).start()
    scheduler = None
    # Round 9: queue mode re-runs from the worker; an inline server runs its own small scheduler
    if settings.run_mode == "inline" and settings.regression_poll_seconds > 0:
        scheduler = RegressionScheduler(session.SessionLocal, _inline_starter)
        threading.Thread(target=thread_target(scheduler.loop), daemon=True).start()
    yield
    if scheduler is not None:
        scheduler.stop.set()


app = FastAPI(
    lifespan=lifespan,
    title="LoopForge",
    version=__version__,
    description="Autonomous, feedback-driven AI software engineering platform.",
)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "If-Match", "Idempotency-Key"],
    expose_headers=[
        "ETag",
        "X-Request-ID",
        "Idempotent-Replay",
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-Total-Count",
        "Link",
    ],  # fmt: skip
)
install_error_handlers(app)
app.include_router(api_v1)
app.include_router(ws.router)
app.include_router(metrics.router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok", "version": __version__}


@app.get("/health/ready", tags=["ops"])
def ready() -> dict[str, Any]:
    """Readiness: the database is reachable."""
    try:
        with session.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from None
    return {"status": "ready"}
