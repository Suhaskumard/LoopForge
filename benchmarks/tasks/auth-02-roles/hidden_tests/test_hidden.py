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


def token_for(client, email, role):
    assert register(client, email, role=role).status_code == 201
    return login(client, email).json()["access_token"]


def test_role_defaults_to_user_and_is_returned(client):
    r = register(client)
    assert r.status_code == 201 and r.json()["role"] == "user"


def test_invalid_role_is_422(client):
    assert register(client, role="superuser").status_code == 422


def test_profile_shows_role(client):
    t = token_for(client, "ann@example.com", "user")
    assert client.get("/profile", headers=bearer(t)).json() == {"email": "ann@example.com", "role": "user"}


def test_admin_can_list_users_and_user_cannot(client):
    admin = token_for(client, "root@example.com", "admin")
    user = token_for(client, "bob@example.com", "user")
    ok = client.get("/admin/users", headers=bearer(admin))
    assert ok.status_code == 200 and ok.json() == ["bob@example.com", "root@example.com"]
    assert client.get("/admin/users", headers=bearer(user)).status_code == 403


def test_anonymous_admin_access_is_401_not_403(client):
    assert client.get("/admin/users").status_code == 401


def test_role_in_token_cannot_be_forged_by_a_user(client):
    token_for(client, "bob@example.com", "user")
    forged = jwt.encode({"sub": "bob@example.com", "role": "admin", "exp": int(time.time()) + 60}, SECRET, algorithm=ALGORITHM)
    assert client.get("/admin/users", headers=bearer(forged)).status_code == 403
