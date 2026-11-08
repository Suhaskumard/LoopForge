"""Outbound email (Phase 15, ADR-0022). Backends: console (dev), memory (tests), smtp (real)."""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("loopforge.mail")


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


# Messages sent by the "memory" backend; tests (and the e2e demo server) read this.
outbox: list[Mail] = []


def _smtp_send(mail: Mail) -> None:  # pragma: no cover - needs a real server (Mailpit test)
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg.set_content(mail.body)
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def send(to: str, subject: str, body: str) -> bool:
    """Send one message. Never raises: a mail failure must not break the request that caused it."""
    mail = Mail(to=to, subject=subject, body=body)
    try:
        if settings.mail_backend == "memory":
            outbox.append(mail)
        elif settings.mail_backend == "smtp":
            _smtp_send(mail)  # pragma: no cover
        else:
            log.info("mail to=%s subject=%s\n%s", to, subject, body)
    except Exception:  # noqa: BLE001
        log.exception("mail delivery failed")
        return False
    return True


def link(path: str, token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/{path.lstrip('/')}?token={token}"


def send_verification(to: str, token: str) -> bool:
    return send(
        to,
        "Verify your LoopForge email",
        "Confirm your address to finish setting up your account:\n"
        f"{link('verify-email', token)}\n\n"
        f"The link works once and expires in {settings.verify_token_ttl_hours} hours.",
    )


def send_reset(to: str, token: str) -> bool:
    return send(
        to,
        "Reset your LoopForge password",
        f"Choose a new password:\n{link('reset-password', token)}\n\n"
        f"The link works once and expires in {settings.reset_token_ttl_minutes} minutes. "
        "If you did not ask for this, ignore this message.",
    )


def send_invite(to: str, org_name: str, role: str, token: str) -> bool:
    return send(
        to,
        f"You are invited to {org_name} on LoopForge",
        f"You were invited to join {org_name} as {role}.\n{link('accept-invite', token)}\n\n"
        f"The link expires in {settings.invite_ttl_days} days. Sign in (or sign up) with this "
        "email address to accept.",
    )
