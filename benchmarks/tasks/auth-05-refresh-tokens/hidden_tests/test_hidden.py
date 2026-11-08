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


def tokens(client):
    register(client)
    return login(client).json()


def test_login_returns_two_different_tokens(client):
    t = tokens(client)
    assert t["access_token"] != t["refresh_token"]
    a = jwt.decode(t["access_token"], SECRET, algorithms=[ALGORITHM])
    r = jwt.decode(t["refresh_token"], SECRET, algorithms=[ALGORITHM])
    assert r["exp"] > a["exp"]


def test_refresh_issues_a_working_access_token(client):
    t = tokens(client)
    r = client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    assert client.get("/me", headers=bearer(r.json()["access_token"])).status_code == 200


def test_access_token_cannot_be_used_to_refresh(client):
    t = tokens(client)
    assert client.post("/auth/refresh", json={"refresh_token": t["access_token"]}).status_code == 401


def test_refresh_token_cannot_call_protected_endpoints(client):
    t = tokens(client)
    assert client.get("/me", headers=bearer(t["refresh_token"])).status_code == 401


def test_garbage_refresh_token_is_401(client):
    tokens(client)
    assert client.post("/auth/refresh", json={"refresh_token": "nope"}).status_code == 401


def test_expired_refresh_token_is_401(client):
    tokens(client)
    old = jwt.encode({"sub": "ann@example.com", "typ": "refresh", "exp": int(time.time()) - 5}, SECRET, algorithm=ALGORITHM)
    assert client.post("/auth/refresh", json={"refresh_token": old}).status_code == 401
