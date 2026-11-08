"""Tiny stdlib HTTP server exposing this process's metrics (used by the worker, Phase 12).

A worker has no web framework, but its counters (LLM calls, sandbox runs, lease takeovers, jobs
finished) live in its own process, so it serves them itself on `WORKER_METRICS_PORT`. It
listens on `WORKER_METRICS_HOST` (default 127.0.0.1; containers set 0.0.0.0 so a scraper can
reach it). It has no authentication: protect it with network policy.
"""

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.utils.metrics import REGISTRY

log = logging.getLogger("loopforge.metrics")
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path.split("?", 1)[0] != "/metrics":
            self.send_error(404)
            return
        body = REGISTRY.render().encode()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - keep scrapes quiet
        return


def start(port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="metrics").start()
    log.info("worker metrics on :%s/metrics", server.server_address[1])
    return server
