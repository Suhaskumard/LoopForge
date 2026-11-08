"""Phase 15: real SMTP delivery to a mail catcher (Mailpit). Skipped unless SMTP_TEST_HOST is set.

CI runs Mailpit as a service container; locally:
    docker run -p 1025:1025 -p 8025:8025 axllent/mailpit
    SMTP_TEST_HOST=localhost SMTP_TEST_PORT=1025 MAILPIT_API=http://localhost:8025 \
        pytest tests/integration/test_phase15_smtp.py
"""

import os
import uuid

import httpx
import pytest

from app.config import settings
from app.services import mail_service

needs_catcher = pytest.mark.skipif(
    not os.environ.get("SMTP_TEST_HOST"), reason="needs a real SMTP catcher (SMTP_TEST_HOST)"
)


@needs_catcher
def test_a_verification_mail_really_arrives_over_smtp(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", os.environ["SMTP_TEST_HOST"])
    monkeypatch.setattr(settings, "smtp_port", int(os.environ.get("SMTP_TEST_PORT", "1025")))
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_user", "")
    to = f"smtp-{uuid.uuid4().hex[:8]}@example.com"

    assert mail_service.send_verification(to, "tok-" + uuid.uuid4().hex) is True

    api = os.environ.get("MAILPIT_API", "http://localhost:8025")
    messages = httpx.get(f"{api}/api/v1/search", params={"query": f"to:{to}"}, timeout=10).json()
    assert messages["messages_count"] == 1
    got = messages["messages"][0]
    assert got["Subject"] == "Verify your LoopForge email"
    body = httpx.get(f"{api}/api/v1/message/{got['ID']}", timeout=10).json()["Text"]
    assert "verify-email?token=tok-" in body


def test_an_unreachable_smtp_server_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)  # nothing listens here
    monkeypatch.setattr(settings, "smtp_timeout_seconds", 1.0)
    assert mail_service.send("a@example.com", "s", "b") is False
