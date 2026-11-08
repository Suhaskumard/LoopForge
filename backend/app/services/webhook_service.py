"""Signed outbound webhooks with retry (Phase 11, ADR-0018).

Signature header: `X-LoopForge-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`.
Receivers verify with `verify_signature`, which compares in constant time and rejects timestamps
outside a tolerance window (replay protection). Targets are untrusted URLs: https only, no
credentials, and every resolved address must be public (SSRF), redirects are never followed.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import WebhookDelivery, WebhookEndpoint
from app.utils.redact import redact

log = logging.getLogger("loopforge.webhooks")

EVENTS = (
    "task.completed",
    "task.failed",
    "task.escalated",
    "publish.requested",
    "publish.approved",
    "publish.rejected",
    "publish.pushed",
    "approval.needed",
    "quota.near_limit",
    "ping",
)
SIGNATURE_HEADER = "X-LoopForge-Signature"


class WebhookUrlError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---- signing -----------------------------------------------------------------------------------


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(
    secret: str,
    body: bytes,
    header: str,
    *,
    tolerance: int | None = None,
    now: float | None = None,
) -> bool:
    tolerance = settings.webhook_signature_tolerance_seconds if tolerance is None else tolerance
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts["t"])
        supplied = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts) > tolerance:
        return False
    expected = sign(secret, body, ts).split("v1=", 1)[1]
    return hmac.compare_digest(expected, supplied)


# ---- target validation -------------------------------------------------------------------------


def validate_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise WebhookUrlError("webhook URL must be https")
    if parts.username or parts.password:
        raise WebhookUrlError("webhook URL must not contain credentials")
    if settings.webhook_allow_private_hosts:
        return
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except OSError:
        raise WebhookUrlError("webhook host could not be resolved") from None
    for addr in addrs:
        if not ipaddress.ip_address(str(addr).split("%")[0]).is_global:
            raise WebhookUrlError("webhook host resolves to a non-public address")


# ---- endpoints and events ----------------------------------------------------------------------


def create_endpoint(
    db: Session, org_id: uuid.UUID, url: str, events: list[str], fmt: str
) -> WebhookEndpoint:
    validate_url(url)
    unknown = set(events) - set(EVENTS)
    if unknown:
        raise WebhookUrlError(f"unknown event(s): {', '.join(sorted(unknown))}")
    ep = WebhookEndpoint(
        org_id=org_id, url=url, secret="whsec_" + secrets.token_urlsafe(32), events=events,
        format=fmt,
    )  # fmt: skip
    db.add(ep)
    db.commit()
    return ep


def emit(db: Session, org_id: uuid.UUID, event: str, data: dict[str, Any]) -> int:
    """Queue a delivery for every matching active endpoint. Returns how many were queued."""
    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.org_id == org_id, WebhookEndpoint.active.is_(True)
        )
    )
    queued = 0
    for ep in endpoints:
        if ep.events and event not in ep.events:
            continue
        payload = {
            "id": str(uuid.uuid4()),
            "event": event,
            "created_at": _now().isoformat(timespec="seconds") + "Z",
            "data": json.loads(redact(json.dumps(data, default=str))),
        }
        db.add(WebhookDelivery(endpoint_id=ep.id, org_id=org_id, event=event, payload=payload))
        queued += 1
    if queued:
        db.commit()
    return queued


def emit_safely(db: Session, org_id: uuid.UUID, event: str, data: dict[str, Any]) -> None:
    """Webhooks must never change the outcome of the action that triggered them."""
    try:
        emit(db, org_id, event, data)
    except Exception:
        log.exception("could not queue webhook %s", event)
        db.rollback()


# ---- delivery ----------------------------------------------------------------------------------


def _body(ep: WebhookEndpoint, payload: dict[str, Any]) -> bytes:
    if ep.format == "slack":
        text = f"LoopForge: {payload['event']} - " + ", ".join(
            f"{k}={v}" for k, v in payload["data"].items() if isinstance(v, (str, int, float))
        )
        return json.dumps({"text": text}).encode()
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def deliver(
    db: Session, delivery: WebhookDelivery, http: httpx.Client | None = None
) -> WebhookDelivery:
    ep = db.get(WebhookEndpoint, delivery.endpoint_id)
    delivery.attempts += 1
    error = ""
    status_code: int | None = None
    if ep is None or not ep.active:
        error = "endpoint removed or disabled"
        delivery.attempts = settings.webhook_max_attempts  # no point retrying
    else:
        body = _body(ep, delivery.payload)
        client = http or httpx.Client(timeout=settings.webhook_timeout_seconds,
                                      follow_redirects=False)  # fmt: skip
        try:
            validate_url(ep.url)  # re-checked on every attempt (DNS can change)
            resp = client.post(
                ep.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: sign(ep.secret, body),
                    "X-LoopForge-Event": delivery.event,
                    "X-LoopForge-Delivery": str(delivery.id),
                },
            )
            status_code = resp.status_code
            if not 200 <= resp.status_code < 300:
                error = f"HTTP {resp.status_code}"
        except (httpx.HTTPError, WebhookUrlError) as exc:
            error = type(exc).__name__ if isinstance(exc, httpx.HTTPError) else str(exc)
        finally:
            if http is None:
                client.close()
    delivery.response_status = status_code
    delivery.last_error = error
    if not error:
        delivery.status = "delivered"
    elif delivery.attempts >= settings.webhook_max_attempts:
        delivery.status = "failed"
    else:
        delay = settings.webhook_backoff_base_seconds * (2 ** (delivery.attempts - 1))
        delivery.next_attempt_at = _now() + timedelta(seconds=delay)
    db.commit()
    return delivery


def deliver_due(db: Session, http: httpx.Client | None = None, limit: int = 20) -> int:
    due = list(
        db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= _now())
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
    )
    for d in due:
        deliver(db, d, http)
    return len(due)
