from hypothesis import given
from hypothesis import strategies as st

from app.utils.redact import REDACTED, contains_secret, redact

SECRETS = [
    "sk-proj-abcdefghijklmnopqrstuvwx1234",
    "sk-abcdefghijklmnop1234567890",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_" + "a1B2c3D4e5" * 4,
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    "xoxb-1234567890-abcdefghij",
]


def test_known_token_shapes_are_removed():
    for s in SECRETS:
        out = redact(f"connecting with {s} now")
        assert s not in out and REDACTED in out, s


def test_pem_block_is_removed_even_when_unterminated():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"
    assert "MIIEow" not in redact(f"key:\n{pem}\nafter")
    assert "MIIEow" not in redact("-----BEGIN PRIVATE KEY-----\nMIIEow")
    assert "after" in redact(f"{pem}\nafter")


def test_assignments_keep_the_key_but_hide_the_value():
    for line in (
        "password=hunter2222",
        'DB_PASSWORD: "s3cr3t-value"',
        "api_key = 'abc123xyz'",
        "OPENAI_API_KEY=sk-live-whatever12345678",
        "token: abcdef12345",
    ):
        out = redact(line)
        assert REDACTED in out
        assert "hunter2222" not in out and "s3cr3t-value" not in out and "abc123xyz" not in out
    assert redact("password=hunter2222").startswith("password=")


def test_bearer_header_keeps_scheme():
    out = redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123")
    assert out == f"Authorization: Bearer {REDACTED}"


def test_ordinary_text_is_untouched():
    for text in (
        "def add(a, b):\n    return a + b\n",
        "tests/test_routes.py::test_update FAILED - assert 404 == 200",
        "The password must be at least 8 characters",
        "token_version increments on logout",
        "",
    ):
        assert redact(text) == text, text
        assert not contains_secret(text)


@given(st.sampled_from(SECRETS), st.text(max_size=40), st.text(max_size=40))
def test_secret_never_survives_arbitrary_surroundings(secret, before, after):
    assert secret not in redact(f"{before} {secret} {after}")


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200))
def test_redaction_is_idempotent(text):
    once = redact(text)
    assert redact(once) == once
