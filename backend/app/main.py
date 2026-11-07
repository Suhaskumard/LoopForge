import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status
from sqlalchemy import text

from app.api.errors import install_error_handlers
from app.api.v1 import agents, auth, projects, runs, tasks
from app.config import settings
from app.database import session
from app.middleware import RequestContextMiddleware
from app.utils.logging import configure_logging

configure_logging()

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth.router)
api_v1.include_router(projects.router)
api_v1.include_router(tasks.router)
api_v1.include_router(runs.router)
api_v1.include_router(runs.iterations_router)
api_v1.include_router(agents.router)

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
    version="0.4.0",
    description="Autonomous, feedback-driven AI software engineering platform.",
)
app.add_middleware(RequestContextMiddleware)
install_error_handlers(app)
app.include_router(api_v1)


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
