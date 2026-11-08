import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import ALGORITHM, SECRET
from app.main import app


@pytest.fixture()
def client():
    import app.store as store

    store.USERS.clear()
    for name in ("FAILED", "ATTEMPTS"):
        if hasattr(store, name):
            getattr(store, name).clear()
    return TestClient(app)


def register(client, email="ann@example.com", password="Passw0rd!long", **extra):
    return client.post("/auth/register", json={"email": email, "password": password, **extra})


def login(client, email="ann@example.com", password="Passw0rd!long"):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_reports_a_ten_minute_lifetime(client):
    register(client)
    body = login(client).json()
    assert body["expires_in"] == 600
    claims = jwt.decode(body["access_token"], SECRET, algorithms=[ALGORITHM])
    assert claims["exp"] - claims["iat"] == 600


def test_an_expired_token_is_401(client):
    register(client)
    old = jwt.encode({"sub": "ann@example.com", "iat": int(time.time()) - 700, "exp": int(time.time()) - 100}, SECRET, algorithm=ALGORITHM)
    assert client.get("/me", headers=bearer(old)).status_code == 401


def test_a_token_without_exp_is_rejected(client):
    register(client)
    forever = jwt.encode({"sub": "ann@example.com"}, SECRET, algorithm=ALGORITHM)
    assert client.get("/me", headers=bearer(forever)).status_code == 401


def test_a_fresh_token_works(client):
    register(client)
    t = login(client).json()["access_token"]
    assert client.get("/me", headers=bearer(t)).status_code == 200


def test_alg_none_tokens_are_rejected(client):
    register(client)
    import base64, json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    unsigned = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"sub": "ann@example.com", "exp": int(time.time()) + 600}) + "."
    assert client.get("/me", headers=bearer(unsigned)).status_code == 401


def test_token_for_a_deleted_user_is_401(client):
    register(client)
    t = login(client).json()["access_token"]
    import app.store as store

    store.USERS.clear()
    assert client.get("/me", headers=bearer(t)).status_code == 401
