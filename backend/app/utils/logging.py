"""JSON logging with correlation ids (Phase 12, ADR-0019).

Every line carries `request_id`; lines written while a task or job is being processed also
carry `task_id` / `job_id`. An API request that enqueues a job stores its request id on the
job, and the worker restores it, so one id links the HTTP request to the worker's log lines.

ContextVars do not cross thread boundaries on their own: start threads through `thread_target` (or
`copy_context().run`) so heartbeat/resume threads keep the ids of the code that started them.
"""

import json
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
task_id_var: ContextVar[str] = ContextVar("task_id", default="-")
job_id_var: ContextVar[str] = ContextVar("job_id", default="-")

_OPTIONAL = (("task_id", task_id_var), ("job_id", job_id_var))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, var in _OPTIONAL:  # only when set, so ordinary request lines stay compact
            value = var.get()
            if value != "-":
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


@contextmanager
def bind(
    *, request_id: str | None = None, task_id: object = None, job_id: object = None
) -> Iterator[None]:
    """Set correlation ids for the duration of a block, restoring the previous values after."""
    tokens = []
    if request_id:
        tokens.append((request_id_var, request_id_var.set(str(request_id))))
    if task_id is not None:
        tokens.append((task_id_var, task_id_var.set(str(task_id))))
    if job_id is not None:
        tokens.append((job_id_var, job_id_var.set(str(job_id))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def thread_target(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a thread target so it runs in a copy of the *current* context (ids carry over)."""
    ctx = copy_context()

    def run(*args: Any, **kwargs: Any) -> Any:
        return ctx.run(fn, *args, **kwargs)

    return run


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
