"""TOTP second factor (Phase 17, RFC 6238 / RFC 4226) with single-use recovery codes.

* SHA-1, 6 digits, 30 s step (what every authenticator app supports), +-1 step of clock skew.
* A code is accepted at most once: the accepted time-step is stored and only a later one is valid.
* The secret is encrypted with the key ring; recovery codes are stored only as SHA-256 hashes.
* Not phishing-resistant (a real-time relay defeats any OTP); WebAuthn is out of scope (ADR-0024).
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database.models import Organization, User
from app.utils.keyring import KeyUnavailable
from app.utils.security import decrypt_secret, encrypt_secret

STEP_SECONDS = 30
DIGITS = 6
SKEW_STEPS = 1
RECOVERY_CODES = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()  # nosec B303
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def totp_at(secret_b32: str, at: float) -> str:
    return _hotp(secret_b32, int(at // STEP_SECONDS))


def provisioning_uri(secret_b32: str, email: str, issuer: str = "LoopForge") -> str:
    label = urllib.parse.quote(f"{issuer}:{email}")
    query = urllib.parse.urlencode({"secret": secret_b32, "issuer": issuer})
    return f"otpauth://totp/{label}?{query}"


def enabled(user: User) -> bool:
    return user.totp_enabled_at is not None


def start_enrolment(db: Session, user: User) -> str:
    """Create (or replace, while not yet active) the pending secret. Returns it once."""
    if enabled(user):
        raise ValueError("MFA is already enabled")
    secret = new_secret()
    user.totp_secret_enc = encrypt_secret(secret)
    db.commit()
    return secret


def _match_step(user: User, code: str, now: float) -> int | None:
    if not user.totp_secret_enc or not (code.isdigit() and len(code) == DIGITS):
        return None
    try:
        secret = decrypt_secret(user.totp_secret_enc)
    except KeyUnavailable:
        return None
    current = int(now // STEP_SECONDS)
    found: int | None = None
    for step in range(current - SKEW_STEPS, current + SKEW_STEPS + 1):
        if hmac.compare_digest(_hotp(secret, step), code):  # check every step: constant work
            found = step
    return found


def verify_code(db: Session, user: User, code: str, now: float | None = None) -> bool:
    """True once per time-step; a replay of the same (or an earlier) step is refused."""
    step = _match_step(user, code.strip(), time.time() if now is None else now)
    if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
        return False
    user.totp_last_step = step
    db.commit()
    return True


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def _new_recovery_codes() -> list[str]:
    return [
        f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
        for _ in range(RECOVERY_CODES)
    ]


def activate(db: Session, user: User, code: str, now: float | None = None) -> list[str]:
    """Confirm the first code from the authenticator app; returns the recovery codes (once)."""
    if enabled(user) or not user.totp_secret_enc:
        raise ValueError("start enrolment first")
    if not verify_code(db, user, code, now):
        raise ValueError("that code is not valid")
    codes = _new_recovery_codes()
    user.recovery_codes = [_hash(c) for c in codes]
    user.totp_enabled_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return codes


def verify_second_factor(
    db: Session, user: User, code: str, now: float | None = None
) -> str | None:
    """Accept a TOTP code or an unused recovery code. Returns 'totp' / 'recovery' / None."""
    if verify_code(db, user, code, now):
        return "totp"
    h = _hash(code)
    remaining = list(user.recovery_codes or [])
    if h in remaining:
        remaining.remove(h)
        user.recovery_codes = remaining  # reassign: JSON columns do not track in-place changes
        db.commit()
        return "recovery"
    return None


def disable(db: Session, user: User) -> None:
    user.totp_secret_enc = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.recovery_codes = []
    db.commit()


def org_requires_mfa(db: Session, org_id: object) -> bool:
    org = db.get(Organization, org_id)
    return bool(org and org.require_mfa)
