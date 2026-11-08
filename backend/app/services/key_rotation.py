"""Re-encrypt stored secrets under the active key (Phase 17). Idempotent; supports a dry run.

Runbook (docs/operations.md): add the new key to KEYRING_JSON and make it active -> deploy ->
``python -m app.keys_cli rotate`` -> ``keys status`` shows nothing under the old kid -> remove the
old key from the ring on the next deploy.
"""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import OrgIntegration, User, WebhookEndpoint
from app.utils import keyring
from app.utils.keyring import KeyUnavailable


@dataclass
class RotationReport:
    active: str
    dry_run: bool
    rotated: int = 0
    already_current: int = 0
    failed: list[str] = field(default_factory=list)  # "<table>.<column>:<id>" - never the value


def _fields(db: Session) -> list[tuple[str, str, object, str]]:
    out: list[tuple[str, str, object, str]] = []
    for oi in db.scalars(select(OrgIntegration)):
        out.append(("org_integrations", "token_enc", oi, oi.token_enc))
    for u in db.scalars(select(User).where(User.totp_secret_enc.is_not(None))):
        out.append(("users", "totp_secret_enc", u, str(u.totp_secret_enc)))
    for ep in db.scalars(select(WebhookEndpoint)):
        out.append(("webhook_endpoints", "secret", ep, ep.secret))
        if ep.previous_secret:
            out.append(("webhook_endpoints", "previous_secret", ep, ep.previous_secret))
    return out


def status(db: Session) -> dict[str, object]:
    by_kid: Counter[str] = Counter()
    for _t, _c, _row, blob in _fields(db):
        by_kid[keyring.key_id_of(blob) if blob.startswith(keyring.PREFIX) else "legacy"] += 1
    return {"active": keyring.provider().active_kid(), "values_by_key": dict(by_kid)}


def rotate(db: Session, dry_run: bool = False) -> RotationReport:
    active = keyring.provider().active_kid()
    report = RotationReport(active=active, dry_run=dry_run)
    for table, column, row, blob in _fields(db):
        # a pre-17 plaintext webhook secret has no prefix and is not Fernet: treat it as plaintext
        plaintext_webhook = table == "webhook_endpoints" and not _looks_encrypted(blob)
        if (
            not plaintext_webhook
            and keyring.key_id_of(blob) == active
            and blob.startswith(keyring.PREFIX)
        ):
            report.already_current += 1
            continue
        try:
            plain = blob if plaintext_webhook else keyring.decrypt(blob)
        except KeyUnavailable:
            report.failed.append(f"{table}.{column}:{getattr(row, 'id', '?')}")
            continue
        if not dry_run:
            setattr(row, column, keyring.encrypt(plain))
        report.rotated += 1
    if not dry_run:
        db.commit()
    return report


def _looks_encrypted(blob: str) -> bool:
    return blob.startswith(keyring.PREFIX) or blob.startswith("gAAAA")
