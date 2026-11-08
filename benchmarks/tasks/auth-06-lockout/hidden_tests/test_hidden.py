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


def bad(client, n, email="ann@example.com"):
    return [login(client, email, "WrongPass123").status_code for _ in range(n)]


def test_three_failures_are_401_then_the_fourth_attempt_is_429(client):
    register(client)
    assert bad(client, 3) == [401, 401, 401]
    assert login(client, password="WrongPass123").status_code == 429


def test_the_correct_password_is_also_refused_while_locked(client):
    register(client)
    bad(client, 3)
    assert login(client).status_code == 429


def test_success_resets_the_counter(client):
    register(client)
    bad(client, 2)
    assert login(client).status_code == 200
    assert bad(client, 2) == [401, 401]
    assert login(client).status_code == 200


def test_lockout_is_per_account(client):
    register(client)
    register(client, "bob@example.com")
    bad(client, 3)
    assert login(client, "bob@example.com").status_code == 200


def test_lockout_is_case_insensitive_on_email(client):
    register(client)
    bad(client, 2)
    login(client, "ANN@example.com", "WrongPass123")
    assert login(client).status_code == 429


def test_unknown_accounts_are_throttled_too(client):
    assert bad(client, 3, "ghost@example.com") == [401, 401, 401]
    assert login(client, "ghost@example.com", "WrongPass123").status_code == 429
