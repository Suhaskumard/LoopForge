"""Worker service: claims jobs from the queue and drives the feedback loop (ADR-0014).

Run with `python -m app.worker`. Start as many as needed; each job is owned by exactly one worker
and each task's loop by exactly one lease holder. A worker that dies is detected by the others via
its expired lease, and the interrupted task resumes from its checkpoint.
"""

import logging
import signal
import threading
import time

from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import session
from app.execution.sandbox import Sandbox
from app.services import job_service, lease_service, run_service, webhook_service
from app.services.llm_client import LLMClient

log = logging.getLogger("loopforge.worker")


def run_once(
    factory: sessionmaker[Session], llm: LLMClient, sandbox: Sandbox, worker: str | None = None
) -> bool:
    """Claim and execute one job. Returns False when the queue is empty."""
    worker = worker or lease_service.OWNER_ID
    with factory() as db:
        job = job_service.claim_next(db, worker)
        if job is None:
            return False
        job_id, task_id, kind = job.id, job.task_id, job.kind
    outcome = ("done", "")
    try:
        if kind == "start":
            run_service.execute_run(factory, task_id, llm, sandbox)
        elif not run_service.resume_run(factory, task_id, llm, sandbox):
            outcome = ("done", "nothing to resume")
    except Exception as exc:  # execute_run never raises; this is a last line of defence
        log.exception("job %s crashed", job_id)
        outcome = ("failed", type(exc).__name__)
    with factory() as db:
        job_service.finish(db, job_id, *outcome)
    return True


def serve(
    factory: sessionmaker[Session],
    llm: LLMClient,
    sandbox: Sandbox,
    stop: threading.Event,
    recover_every: float = 10.0,
) -> None:
    last_recovery = 0.0
    while not stop.is_set():
        if time.monotonic() - last_recovery >= recover_every:
            last_recovery = time.monotonic()
            try:
                with factory() as db:
                    job_service.recover(db)
            except Exception:
                log.exception("recovery scan failed")
        try:
            with factory() as db:
                webhook_service.deliver_due(db)
        except Exception:
            log.exception("webhook delivery failed")
        try:
            busy = run_once(factory, llm, sandbox)
        except Exception:
            log.exception("worker iteration failed")
            busy = False
        if not busy:
            stop.wait(settings.worker_poll_seconds)


def main() -> None:
    from app.execution.sandbox import get_sandbox_backend
    from app.services.llm_client import get_llm_client
    from app.utils.logging import configure_logging

    configure_logging()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    log.info("worker %s started", lease_service.OWNER_ID)
    serve(session.SessionLocal, get_llm_client(), get_sandbox_backend(), stop)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
