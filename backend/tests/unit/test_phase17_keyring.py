"""Phase 17: key ring - rotation of token-signing and secret-encryption keys without downtime."""

import json
import time

import jwt
import pytest
from cryptography.fernet import Fernet

from app.config import Settings, settings
from app.utils import keyring
from app.utils.keyring import KeyUnavailable
from app.utils.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
)

K1 = "k1-" + "a" * 40
K2 = "k2-" + "b" * 40


def ring(active: str, **keys: str) -> str:
    return json.dumps({"active": active, "keys": keys or {"k1": K1, "k2": K2}})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", "")
    monkeypatch.setattr(settings, "secrets_key", "")


def test_without_a_ring_values_use_the_legacy_key_and_round_trip():
    blob = encrypt_secret("tok")
    assert blob.startswith("v2:legacy:")
    assert decrypt_secret(blob) == "tok"


def test_pre_phase17_ciphertext_still_decrypts(monkeypatch):
    import base64
    import hashlib

    monkeypatch.setattr(settings, "secrets_key", "old-secrets-key")
    old = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"old-secrets-key").digest()))
    assert decrypt_secret(old.encrypt(b"tok").decode()) == "tok"
    assert keyring.key_id_of(old.encrypt(b"x").decode()) == "legacy"


def test_new_writes_use_the_active_key_and_old_values_stay_readable(monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    before = encrypt_secret("one")
    assert keyring.key_id_of(before) == "k1"
    monkeypatch.setattr(settings, "keyring_json", ring("k2"))
    after = encrypt_secret("two")
    assert keyring.key_id_of(after) == "k2"
    assert decrypt_secret(before) == "one" and decrypt_secret(after) == "two"


def test_a_removed_key_is_a_loud_error_not_a_silent_none(monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    blob = encrypt_secret("one")
    monkeypatch.setattr(settings, "keyring_json", ring("k2", k2=K2))
    with pytest.raises(KeyUnavailable, match="not in the key ring"):
        decrypt_secret(blob)


def test_wrong_material_and_malformed_values_raise(monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    blob = encrypt_secret("one")
    monkeypatch.setattr(settings, "keyring_json", ring("k1", k1="z" * 40))
    with pytest.raises(KeyUnavailable, match="does not decrypt"):
        decrypt_secret(blob)
    with pytest.raises(KeyUnavailable, match="malformed"):
        decrypt_secret("v2:onlytwo")


def test_jwts_carry_a_kid_and_survive_rotation(monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    tok = create_access_token("user-1", 3)
    assert jwt.get_unverified_header(tok)["kid"] == "k1"
    monkeypatch.setattr(settings, "keyring_json", ring("k2"))
    claims = decode_access_token(tok)  # signed by the previous key: still valid until it expires
    assert claims and claims["sub"] == "user-1" and claims["tv"] == 3
    assert jwt.get_unverified_header(create_access_token("u"))["kid"] == "k2"


def test_tokens_from_before_the_ring_have_no_kid_and_verify_as_legacy():
    old = jwt.encode(
        {"sub": "u", "tv": 0, "exp": int(time.time()) + 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    assert decode_access_token(old) is not None


def test_unknown_or_forged_kid_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "keyring_json", ring("k1"))
    exp = int(time.time()) + 60
    forged = jwt.encode(
        {"sub": "u", "tv": 0, "exp": exp}, "x" * 40, algorithm="HS256", headers={"kid": "k9"}
    )
    assert decode_access_token(forged) is None
    wrong = jwt.encode(
        {"sub": "u", "tv": 0, "exp": exp}, "x" * 40, algorithm="HS256", headers={"kid": "k1"}
    )
    assert decode_access_token(wrong) is None
    assert decode_access_token("not-a-jwt") is None


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        json.dumps({"active": "k1", "keys": {}}),
        json.dumps({"active": "zz", "keys": {"k1": K1}}),
        json.dumps({"active": "k1", "keys": {"k1": "short"}}),
        json.dumps({"active": "legacy", "keys": {"legacy": K1}}),
        json.dumps({"active": "a:b", "keys": {"a:b": K1}}),
    ],
)
def test_bad_ring_config_is_refused_at_startup(raw):
    with pytest.raises(ValueError, match="KEYRING_JSON"):
        Settings(keyring_json=raw)


def _prod(**kw):
    base = dict(
        environment="production",
        jwt_secret="j" * 40,
        llm_provider="openai",
        sandbox_backend="docker",
        mail_backend="smtp",
    )
    return Settings(**{**base, **kw})


def test_production_requires_a_separate_encryption_key():
    with pytest.raises(ValueError, match="SECRETS_KEY or KEYRING_JSON"):
        _prod()
    with pytest.raises(ValueError, match="must differ"):
        _prod(secrets_key="j" * 40)
    _prod(secrets_key="s" * 40)
    _prod(keyring_json=ring("k1"))
