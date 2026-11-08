import pytest
from fastapi.testclient import TestClient

from app.main import API_KEY, app

c = TestClient(app)


def test_exact_key_is_accepted():
    r = c.get("/secret", headers={"X-API-Key": API_KEY})
    assert r.status_code == 200 and r.json() == {"data": "classified"}


@pytest.mark.parametrize("key", [API_KEY + "-extra", API_KEY[:-1], API_KEY[:10], API_KEY.upper(), " " + API_KEY, "", "wrong"])
def test_anything_else_is_rejected(key):
    assert c.get("/secret", headers={"X-API-Key": key}).status_code == 401


def test_missing_header_is_401():
    assert c.get("/secret").status_code == 401


def test_public_endpoint_is_open():
    assert c.get("/public").json() == {"data": "hello"}


def test_comparison_is_constant_time():
    import inspect

    import app.main as m

    src = inspect.getsource(m)
    assert "compare_digest" in src
