from app.utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)


def test_verify_rejects_malformed_hash():
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_token_roundtrip_and_tamper():
    token = create_access_token("user-1", token_version=3)
    claims = decode_access_token(token)
    assert claims is not None and claims["sub"] == "user-1" and claims["tv"] == 3
    assert decode_access_token(token + "x") is None
    assert decode_access_token("garbage") is None


def test_refresh_tokens_are_random_and_hashed():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 64
    assert hash_refresh_token(a) == hash_refresh_token(a)
    assert hash_refresh_token(a) != a
