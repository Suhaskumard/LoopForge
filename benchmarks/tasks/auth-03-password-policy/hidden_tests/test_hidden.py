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


import pytest as _pytest


@_pytest.mark.parametrize(
    "pw,expected",
    [
        ("Short1a", ["too_short"]),
        ("alllowercase123", ["no_upper"]),
        ("ALLUPPERCASE123", ["no_lower"]),
        ("NoDigitsHereAtAll", ["no_digit"]),
        ("short", ["too_short", "no_upper", "no_digit"]),
    ],
)
def test_violations_are_reported_by_code(client, pw, expected):
    r = register(client, password=pw)
    assert r.status_code == 422
    detail = r.json()["detail"]
    violations = detail["violations"] if isinstance(detail, dict) else None
    assert violations is not None and sorted(violations) == sorted(expected)


def test_a_strong_password_is_accepted_and_hashed(client):
    assert register(client, password="GoodPassw0rd").status_code == 201
    assert login(client, password="GoodPassw0rd").status_code == 200
    import app.store as store

    assert store.USERS["ann@example.com"]["password_hash"].startswith("$2")


def test_exactly_ten_characters_is_enough(client):
    assert register(client, password="Abcdefgh12").status_code == 201
    assert register(client, "bob@example.com", password="Abcdefg12").status_code == 422
