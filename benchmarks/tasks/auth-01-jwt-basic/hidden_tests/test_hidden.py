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


def test_register_login_me_flow(client):
    assert register(client).status_code == 201
    r = login(client)
    assert r.status_code == 200 and r.json()["token_type"].lower() == "bearer"
    me = client.get("/me", headers=bearer(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "ann@example.com"


def test_email_is_case_insensitive_and_unique(client):
    assert register(client, "Ann@Example.com").status_code == 201
    assert register(client, "ann@example.com").status_code == 409
    assert login(client, "ANN@EXAMPLE.COM").status_code == 200


def test_password_is_stored_hashed(client):
    register(client)
    h = next(iter(__import__("app.store", fromlist=["USERS"]).USERS.values()))["password_hash"]
    assert h != "Passw0rd!long" and h.startswith("$2")


def test_wrong_password_and_unknown_user_are_401(client):
    register(client)
    assert login(client, password="WrongPass123").status_code == 401
    assert login(client, "ghost@example.com").status_code == 401


def test_short_password_is_rejected_with_422(client):
    assert register(client, password="short").status_code == 422


def test_me_requires_a_valid_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=bearer("garbage")).status_code == 401
    forged = jwt.encode({"sub": "ann@example.com", "exp": int(time.time()) + 60}, "wrong-secret-key-wrong-secret-key", algorithm=ALGORITHM)
    register(client)
    assert client.get("/me", headers=bearer(forged)).status_code == 401


def test_token_carries_subject_and_expiry(client):
    register(client)
    token = login(client).json()["access_token"]
    claims = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert claims["sub"] == "ann@example.com"
    assert 0 < claims["exp"] - time.time() <= 3600
