"""LoopForge Python client (Phase 18). A thin, typed layer over the REST API (docs/openapi.json).

    from loopforge_sdk import LoopForge
    lf = LoopForge("https://loopforge.example.com", token="lfk_...")
    project = lf.create_project("billing")
    task = lf.create_task(project["id"], "Add an invoice export endpoint with tests")
    lf.start_task(task["id"])
    done = lf.wait_for_task(task["id"])

Behaviour you can rely on:
* **Retries**: 429 (honouring ``Retry-After``), 502/503/504 and transport errors, with exponential backoff.
  A ``POST`` is retried only if it is safe to: the create/start/publish calls send an
  ``Idempotency-Key`` (generated for you, reused across retries), so a retry can never create twice.
* **Pagination**: ``projects()``, ``tasks()`` and friends are iterators that follow ``limit/offset``.
* **Errors**: every non-2xx answer raises a subclass of ``APIError`` carrying ``status``, ``code``,
  ``message`` and ``request_id``.
Any endpoint without a named method is reachable with ``request()`` (see ``UNNAMED`` in the tests).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from .errors import APIError, TransportError, error_for

__version__ = "1.0.0rc1"
TERMINAL = {"COMPLETED", "FAILED", "ESCALATED", "CANCELLED"}
RETRY_STATUS = {429, 502, 503, 504}

# (HTTP method, path template) of every operation that has a named method on LoopForge.
# tests/test_contract.py checks this table against docs/openapi.json in both directions.
OPERATIONS: dict[str, tuple[str, str]] = {
    "register": ("POST", "/api/v1/auth/register"),
    "login": ("POST", "/api/v1/auth/login"),
    "refresh": ("POST", "/api/v1/auth/refresh"),
    "me": ("GET", "/api/v1/auth/me"),
    "orgs": ("GET", "/api/v1/orgs"),
    "org": ("GET", "/api/v1/orgs/{org_id}"),
    "usage": ("GET", "/api/v1/orgs/{org_id}/usage"),
    "usage_report": ("GET", "/api/v1/orgs/{org_id}/usage/report"),
    "usage_report_csv": ("GET", "/api/v1/orgs/{org_id}/usage/report.csv"),
    "members": ("GET", "/api/v1/orgs/{org_id}/members"),
    "create_token": ("POST", "/api/v1/orgs/{org_id}/tokens"),
    "tokens": ("GET", "/api/v1/orgs/{org_id}/tokens"),
    "revoke_token": ("DELETE", "/api/v1/orgs/{org_id}/tokens/{token_id}"),
    "create_webhook": ("POST", "/api/v1/orgs/{org_id}/webhooks"),
    "webhooks": ("GET", "/api/v1/orgs/{org_id}/webhooks"),
    "delete_webhook": ("DELETE", "/api/v1/orgs/{org_id}/webhooks/{webhook_id}"),
    "rotate_webhook_secret": ("POST", "/api/v1/orgs/{org_id}/webhooks/{webhook_id}/rotate"),
    "create_project": ("POST", "/api/v1/projects"),
    "projects": ("GET", "/api/v1/projects"),
    "project": ("GET", "/api/v1/projects/{project_id}"),
    "delete_project": ("DELETE", "/api/v1/projects/{project_id}"),
    "create_task": ("POST", "/api/v1/tasks"),
    "tasks": ("GET", "/api/v1/tasks"),
    "task": ("GET", "/api/v1/tasks/{task_id}"),
    "start_task": ("POST", "/api/v1/tasks/{task_id}/start"),
    "cancel_task": ("POST", "/api/v1/tasks/{task_id}/cancel"),
    "retry_task": ("POST", "/api/v1/tasks/{task_id}/retry"),
    "task_events": ("GET", "/api/v1/tasks/{task_id}/events"),
    "task_report": ("GET", "/api/v1/tasks/{task_id}/report"),
    "task_report_markdown": ("GET", "/api/v1/tasks/{task_id}/report.md"),
    "task_files": ("GET", "/api/v1/tasks/{task_id}/files"),
    "publish": ("POST", "/api/v1/tasks/{task_id}/publish"),
    "publishes": ("GET", "/api/v1/tasks/{task_id}/publish"),
    "health": ("GET", "/health"),
}
IDEMPOTENT_CREATES = {"create_project", "create_task", "start_task", "publish"}


class LoopForge:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        org_id: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        max_backoff: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token, self.org_id = token, org_id
        self.max_retries, self.backoff, self.max_backoff = max_retries, backoff, max_backoff
        self._sleep = sleep
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    # ---- plumbing -------------------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LoopForge:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": f"loopforge-sdk-python/{__version__}"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.org_id:
            h["X-Org-Id"] = self.org_id
        return {**h, **(extra or {})}

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_backoff)
        return min(self.backoff * (2**attempt), self.max_backoff)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send a request with retries; raise ``APIError`` for any non-2xx final answer."""
        extra = dict(headers or {})
        if idempotency_key:
            extra["Idempotency-Key"] = idempotency_key
        retryable = method.upper() != "POST" or bool(idempotency_key)
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        while True:
            try:
                resp = self._http.request(
                    method, path, json=json, data=data, params=clean, headers=self._headers(extra)
                )
            except httpx.TransportError as exc:
                if retryable and attempt < self.max_retries:
                    self._sleep(self._delay(attempt, None))
                    attempt += 1
                    continue
                raise TransportError(f"cannot reach {self.base_url}: {type(exc).__name__}") from None
            retry_after = _retry_after(resp)
            if resp.status_code in RETRY_STATUS and retryable and attempt < self.max_retries:
                self._sleep(self._delay(attempt, retry_after))
                attempt += 1
                continue
            if resp.is_success:
                return resp
            raise _api_error(resp, retry_after)

    def _json(self, method: str, path: str, **kw: Any) -> Any:
        resp = self.request(method, path, **kw)
        return resp.json() if resp.content else None

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, page_size: int = 100
    ) -> Iterator[dict[str, Any]]:
        """Yield every item of a collection endpoint, following ``limit`` / ``offset``."""
        offset = 0
        while True:
            resp = self.request(
                "GET", path, params={**(params or {}), "limit": page_size, "offset": offset}
            )
            items = resp.json()
            yield from items
            total = resp.headers.get("X-Total-Count")
            offset += len(items)
            if not items or len(items) < page_size or (total is not None and offset >= int(total)):
                return

    def _org(self, org_id: str | None) -> str:
        oid = org_id or self.org_id
        if not oid:
            raise ValueError("this call needs an organization: pass org_id= or set LoopForge(org_id=...)")
        return oid

    # ---- auth -----------------------------------------------------------------------------

    def register(self, email: str, password: str) -> dict[str, Any]:
        return self._json("POST", "/api/v1/auth/register", json={"email": email, "password": password})

    def login(self, email: str, password: str, mfa_code: str | None = None) -> dict[str, Any]:
        """Sign in with a password (and a TOTP/recovery code if MFA is on); stores the access token."""
        form = {"username": email, "password": password}
        if mfa_code:
            form["mfa_code"] = mfa_code
        tokens = self._json("POST", "/api/v1/auth/login", data=form)
        self.token = tokens["access_token"]
        return tokens  # type: ignore[no-any-return]

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        tokens = self._json("POST", "/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        self.token = tokens["access_token"]
        return tokens  # type: ignore[no-any-return]

    def me(self) -> dict[str, Any]:
        return self._json("GET", "/api/v1/auth/me")  # type: ignore[no-any-return]

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/health")  # type: ignore[no-any-return]

    # ---- organizations --------------------------------------------------------------------

    def orgs(self) -> list[dict[str, Any]]:
        return self._json("GET", "/api/v1/orgs")  # type: ignore[no-any-return]

    def org(self, org_id: str | None = None) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/orgs/{self._org(org_id)}")  # type: ignore[no-any-return]

    def usage(self, org_id: str | None = None) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/orgs/{self._org(org_id)}/usage")  # type: ignore[no-any-return]

    def usage_report(
        self,
        *,
        group_by: str = "project",
        since: str | None = None,
        until: str | None = None,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """Usage by project/member/agent/model/day. Dates are YYYY-MM-DD (UTC, inclusive)."""
        params = {"group_by": group_by, "from": since, "to": until}
        path = f"/api/v1/orgs/{self._org(org_id)}/usage/report"
        return self._json("GET", path, params=params)  # type: ignore[no-any-return]

    def usage_report_csv(
        self, *, group_by: str = "project", since: str | None = None, until: str | None = None,
        org_id: str | None = None,
    ) -> str:  # fmt: skip
        params = {"group_by": group_by, "from": since, "to": until}
        path = f"/api/v1/orgs/{self._org(org_id)}/usage/report.csv"
        return self.request("GET", path, params=params).text

    def members(self, org_id: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/api/v1/orgs/{self._org(org_id)}/members")

    def create_token(
        self, name: str, scope: str = "developer", expires_days: int | None = None,
        org_id: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """Create an org-bound API token. The secret is in the result ONCE (key ``token``)."""
        body = {"name": name, "scope": scope, "expires_days": expires_days}
        return self._json("POST", f"/api/v1/orgs/{self._org(org_id)}/tokens", json=body)  # type: ignore[no-any-return]

    def tokens(self, org_id: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/api/v1/orgs/{self._org(org_id)}/tokens")

    def revoke_token(self, token_id: str, org_id: str | None = None) -> None:
        self.request("DELETE", f"/api/v1/orgs/{self._org(org_id)}/tokens/{token_id}")

    def create_webhook(
        self, url: str, events: list[str] | None = None, format: str = "json",
        org_id: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """Register a webhook. The signing secret is in the result ONCE (key ``secret``)."""
        body = {"url": url, "events": events or [], "format": format}
        return self._json("POST", f"/api/v1/orgs/{self._org(org_id)}/webhooks", json=body)  # type: ignore[no-any-return]

    def webhooks(self, org_id: str | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/api/v1/orgs/{self._org(org_id)}/webhooks")

    def delete_webhook(self, webhook_id: str, org_id: str | None = None) -> None:
        self.request("DELETE", f"/api/v1/orgs/{self._org(org_id)}/webhooks/{webhook_id}")

    def rotate_webhook_secret(self, webhook_id: str, org_id: str | None = None) -> dict[str, Any]:
        path = f"/api/v1/orgs/{self._org(org_id)}/webhooks/{webhook_id}/rotate"
        return self._json("POST", path)  # type: ignore[no-any-return]

    # ---- projects and tasks ---------------------------------------------------------------

    def create_project(
        self, name: str, *, language: str | None = None, idempotency_key: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:  # fmt: skip
        body = {"name": name, **({"language": language} if language else {}), **fields}
        return self._json(  # type: ignore[no-any-return]
            "POST", "/api/v1/projects", json=body, idempotency_key=idempotency_key or _new_key()
        )

    def projects(self) -> Iterator[dict[str, Any]]:
        return self.paginate("/api/v1/projects")

    def project(self, project_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/projects/{project_id}")  # type: ignore[no-any-return]

    def delete_project(self, project_id: str) -> None:
        self.request("DELETE", f"/api/v1/projects/{project_id}")

    def create_task(
        self, project_id: str, requirement: str, *, idempotency_key: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:  # fmt: skip
        body = {"project_id": project_id, "requirement": requirement, **fields}
        return self._json(  # type: ignore[no-any-return]
            "POST", "/api/v1/tasks", json=body, idempotency_key=idempotency_key or _new_key()
        )

    def tasks(self, **filters: Any) -> Iterator[dict[str, Any]]:
        return self.paginate("/api/v1/tasks", filters)

    def task(self, task_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/tasks/{task_id}")  # type: ignore[no-any-return]

    def start_task(self, task_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._json(  # type: ignore[no-any-return]
            "POST", f"/api/v1/tasks/{task_id}/start", idempotency_key=idempotency_key or _new_key()
        )

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self._json("POST", f"/api/v1/tasks/{task_id}/cancel")  # type: ignore[no-any-return]

    def retry_task(self, task_id: str) -> dict[str, Any]:
        return self._json("POST", f"/api/v1/tasks/{task_id}/retry")  # type: ignore[no-any-return]

    def task_events(self, task_id: str) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/api/v1/tasks/{task_id}/events", page_size=500)

    def task_report(self, task_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/tasks/{task_id}/report")  # type: ignore[no-any-return]

    def task_report_markdown(self, task_id: str) -> str:
        return self.request("GET", f"/api/v1/tasks/{task_id}/report.md").text

    def task_files(self, task_id: str) -> list[dict[str, Any]]:
        return self._json("GET", f"/api/v1/tasks/{task_id}/files")  # type: ignore[no-any-return]

    def publish(
        self, task_id: str, repo: str, base_branch: str = "main", *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        """Ask for a pull request for a COMPLETED task (an approver then approves it)."""
        return self._json(  # type: ignore[no-any-return]
            "POST",
            f"/api/v1/tasks/{task_id}/publish",
            json={"repo": repo, "base_branch": base_branch},
            idempotency_key=idempotency_key or _new_key(),
        )

    def publishes(self, task_id: str) -> Iterator[dict[str, Any]]:
        return self.paginate(f"/api/v1/tasks/{task_id}/publish")

    def wait_for_task(
        self, task_id: str, *, timeout: float = 1800.0, poll: float = 3.0
    ) -> dict[str, Any]:
        """Block until the task reaches a terminal status; raises ``TimeoutError`` otherwise."""
        deadline = time.monotonic() + timeout
        while True:
            task = self.task(task_id)
            if task["status"] in TERMINAL:
                return task
            if time.monotonic() >= deadline:
                raise TimeoutError(f"task {task_id} still {task['status']} after {timeout}s")
            self._sleep(poll)


def _new_key() -> str:
    return uuid.uuid4().hex


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _api_error(resp: httpx.Response, retry_after: float | None) -> APIError:
    code = message = None
    body: Any = None
    try:
        body = resp.json()
    except ValueError:
        message = resp.text[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):  # the LoopForge envelope
            code, message = err.get("code"), err.get("message")
        elif "detail" in body:  # SCIM and framework errors
            message = str(body["detail"])
    return error_for(resp.status_code)(
        resp.status_code,
        message or resp.reason_phrase,
        code=code,
        request_id=resp.headers.get("X-Request-ID"),
        body=body,
        retry_after=retry_after,
    )
