"""Tiny stdlib HTTP server exposing this process's metrics (used by the worker, Phase 12).

A worker has no web framework, but its counters (LLM calls, sandbox runs, lease takeovers, jobs
finished) live in its own process, so it serves them itself on `WORKER_METRICS_PORT`. It
listens on `WORKER_METRICS_HOST` (default 127.0.0.1; containers set 0.0.0.0 so a scraper can
reach it). It has no authentication unless `WORKER_METRICS_TOKEN` is set, which then
requires a bearer token. Without a token, protect it with network policy.
"""

import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.utils.metrics import REGISTRY

log = logging.getLogger("loopforge.metrics")
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class _Handler(BaseHTTPRequestHandler):
    token: str | None = None  # set by start(): when set, a bearer token is required

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path.split("?", 1)[0] != "/metrics":
            self.send_error(404)
            return
        if self.token:
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not secrets.compare_digest(supplied, self.token):
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        body = REGISTRY.render().encode()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - keep scrapes quiet
        return


def start(port: int, host: str = "127.0.0.1", token: str | None = None) -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"token": token})  # per-server token, no global state
    server = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="metrics").start()
    log.info("worker metrics on :%s/metrics", server.server_address[1])
    return server
