import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings
from app.utils import keyring
from app.utils.keyring import KeyUnavailable


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(subject: str, token_version: int = 0) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    return sign_claims({"sub": subject, "tv": token_version, "exp": exp})


def sign_claims(claims: dict[str, object]) -> str:
    """Sign with the active ring key and put its id in the ``kid`` header."""
    p = keyring.provider()
    key = p.get(p.active_kid())
    assert key is not None  # nosec B101 - provider contract
    return jwt.encode(
        claims, key.sign_secret, algorithm=settings.jwt_algorithm, headers={"kid": key.kid}
    )


def verify_claims(token: str) -> dict[str, object]:
    """Verify against the key named by the token's ``kid`` (no kid = a pre-ring token = legacy)."""
    kid = jwt.get_unverified_header(token).get("kid", keyring.LEGACY)
    key = keyring.provider().get(kid) if isinstance(kid, str) else None
    if key is None:
        raise jwt.InvalidTokenError("unknown signing key")
    payload: dict[str, object] = jwt.decode(
        token, key.sign_secret, algorithms=[settings.jwt_algorithm]
    )
    return payload


def decode_access_token(token: str) -> dict[str, object] | None:
    """Return the verified claims, or None if the token is invalid/expired."""
    try:
        payload = verify_claims(token)
    except jwt.PyJWTError:
        return None
    return payload if "sub" in payload else None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def encrypt_secret(plain: str) -> str:
    return keyring.encrypt(plain)


def decrypt_secret(blob: str) -> str:
    """Raises KeyUnavailable (never returns a silent None) when the key cannot decrypt the value."""
    return keyring.decrypt(blob)


__all__ = ["KeyUnavailable"]
