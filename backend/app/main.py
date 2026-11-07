from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status
from sqlalchemy import text

from app.api.errors import install_error_handlers
from app.api.v1 import agents, auth, projects, runs, tasks
from app.database import session
from app.middleware import RequestContextMiddleware
from app.utils.logging import configure_logging

configure_logging()

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(auth.router)
api_v1.include_router(projects.router)
api_v1.include_router(tasks.router)
api_v1.include_router(runs.router)
api_v1.include_router(agents.router)

app = FastAPI(
    title="LoopForge",
    version="0.3.0",
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
