"""Key ring (Phase 17): named keys with an active one, so keys can be rotated without downtime.

* ``KEYRING_JSON`` = ``{"active": "k2", "keys": {"k1": "<secret>", "k2": "<secret>"}}``.
* The implicit key ``legacy`` is what every earlier release used (JWT_SECRET to sign,
  SECRETS_KEY or JWT_SECRET to encrypt). It stays in the ring so old tokens and ciphertext work.
* Encrypted values are ``v2:<kid>:<fernet token>``; a value without that prefix is legacy.
* Key material only comes from the process environment. ``KeyProvider`` is where a KMS adapter
  would plug in (fetch material by kid); only the ``local`` provider is implemented and tested.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

LEGACY = "legacy"
PREFIX = "v2:"


class KeyUnavailable(Exception):
    """The key needed for this value/token is not in the ring (or does not match)."""


@dataclass(frozen=True)
class Key:
    kid: str
    sign_secret: str
    enc_secret: str

    def fernet(self) -> Fernet:
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(self.enc_secret.encode()).digest()))


class KeyProvider(Protocol):
    """Where key material comes from. A KMS adapter implements this; none ships (see ADR-0024)."""

    def active_kid(self) -> str: ...

    def get(self, kid: str) -> Key | None: ...


class LocalKeyProvider:
    def __init__(self, keyring_json: str, jwt_secret: str, secrets_key: str) -> None:
        self._keys: dict[str, Key] = {LEGACY: Key(LEGACY, jwt_secret, secrets_key or jwt_secret)}
        self._active = LEGACY
        if keyring_json.strip():
            data = parse_keyring(keyring_json)
            for kid, material in data["keys"].items():
                self._keys[kid] = Key(kid, material, material)
            self._active = data["active"]

    def active_kid(self) -> str:
        return self._active

    def get(self, kid: str) -> Key | None:
        return self._keys.get(kid)

    def kids(self) -> list[str]:
        return sorted(self._keys)


def parse_keyring(raw: str) -> dict[str, Any]:
    """Validate KEYRING_JSON; raises ValueError with a message that names the problem."""
    try:
        data = json.loads(raw)
        keys = data["keys"]
        active = data["active"]
        if (
            not isinstance(keys, dict)
            or not keys
            or not isinstance(active, str)
            or active not in keys
            or any(not isinstance(k, str) or not k or ":" in k or k == LEGACY for k in keys)
            or any(not isinstance(v, str) or len(v) < 32 for v in keys.values())
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError(
            'KEYRING_JSON must be {"active": "<kid>", "keys": {"<kid>": "<secret >=32 chars>"}} '
            "with the active kid present, and kids without ':' that are not 'legacy'"
        ) from None
    return {"active": active, "keys": keys}


_cache: tuple[tuple[str, str, str], LocalKeyProvider] | None = None


def provider() -> KeyProvider:
    global _cache
    sig = (settings.keyring_json, settings.jwt_secret, settings.secrets_key)
    if _cache is None or _cache[0] != sig:
        _cache = (sig, LocalKeyProvider(*sig))
    return _cache[1]


def encrypt(plain: str) -> str:
    key = provider().get(provider().active_kid())
    if key is None:  # pragma: no cover - provider contract
        raise KeyUnavailable(provider().active_kid())
    return f"{PREFIX}{key.kid}:{key.fernet().encrypt(plain.encode()).decode()}"


def key_id_of(blob: str) -> str:
    """The kid a stored value was encrypted under (``legacy`` for pre-Phase-17 ciphertext)."""
    if blob.startswith(PREFIX):
        return blob[len(PREFIX) :].split(":", 1)[0]
    return LEGACY


def decrypt(blob: str) -> str:
    if blob.startswith(PREFIX):
        try:
            _, kid, token = blob.split(":", 2)
        except ValueError:
            raise KeyUnavailable("malformed ciphertext") from None
    else:
        kid, token = LEGACY, blob
    key = provider().get(kid)
    if key is None:
        raise KeyUnavailable(f"key '{kid}' is not in the key ring")
    try:
        return key.fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise KeyUnavailable(f"key '{kid}' does not decrypt this value") from None
