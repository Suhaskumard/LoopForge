import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import LoginAttempt, RefreshToken
from app.services.auth_service import _now
from tests.conftest import register_and_login


def _login(client, email="u@x.com", password="password123"):
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200
    return r.json()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_login_returns_token_pair(client):
    body = _login(client)
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert body["access_token"] and body["refresh_token"]


def test_refresh_rotates_and_old_token_dies(client):
    t1 = _login(client)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()
    assert t2["refresh_token"] != t1["refresh_token"]
    assert client.get("/api/v1/auth/me", headers=_bearer(t2["access_token"])).status_code == 200


def test_refresh_token_reuse_revokes_whole_family(client):
    t1 = _login(client)
    t2 = client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    # attacker replays the already-spent token ...
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert replay.status_code == 401
    # ... so the legitimately rotated token is dead too
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code
        == 401
    )


def test_unknown_and_expired_refresh_tokens_rejected(client):
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"}).status_code == 401
    t = _login(client)
    with Session(client.engine) as s:
        row = s.scalars(select(RefreshToken)).first()
        row.expires_at = _now() - timedelta(seconds=1)
        s.commit()
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code
        == 401
    )


def test_logout_revokes_refresh_family(client):
    t = _login(client)
    assert (
        client.post("/api/v1/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code
        == 204
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code
        == 401
    )
    # logging out an unknown token is a harmless no-op
    assert client.post("/api/v1/auth/logout", json={"refresh_token": "zzz"}).status_code == 204


def test_logout_all_invalidates_access_and_refresh_tokens(client):
    t = _login(client)
    assert (
        client.post("/api/v1/auth/logout-all", headers=_bearer(t["access_token"])).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me", headers=_bearer(t["access_token"])).status_code == 401
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code
        == 401
    )
    # a fresh login works again
    again = client.post(
        "/api/v1/auth/login", data={"username": "u@x.com", "password": "password123"}
    )
    assert (
        client.get("/api/v1/auth/me", headers=_bearer(again.json()["access_token"])).status_code
        == 200
    )


def test_refresh_tokens_stored_hashed_only(client):
    t = _login(client)
    with Session(client.engine) as s:
        hashes = [r.token_hash for r in s.scalars(select(RefreshToken))]
    assert hashes and t["refresh_token"] not in hashes


def test_rate_limit_state_lives_in_database_and_expires(client):
    register_and_login(client, "rl2@x.com")
    for _ in range(5):
        client.post("/api/v1/auth/login", data={"username": "rl2@x.com", "password": "bad"})
    with Session(client.engine) as s:
        assert len(list(s.scalars(select(LoginAttempt)))) == 5
        for a in s.scalars(select(LoginAttempt)):
            a.created_at = _now() - timedelta(hours=1)  # outside the window
        s.commit()
    ok = client.post(
        "/api/v1/auth/login", data={"username": "rl2@x.com", "password": "password123"}
    )
    assert ok.status_code == 200
    with Session(client.engine) as s:
        assert list(s.scalars(select(LoginAttempt))) == []  # cleared on success


def test_errors_use_uniform_envelope(client):
    r = client.get("/api/v1/projects/" + str(uuid.uuid4()))
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "unauthorized" and err["request_id"] and err["message"]
    h = register_and_login(client, "env@x.com")
    nf = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=h)
    assert nf.json()["error"]["code"] == "not_found"
    bad = client.post("/api/v1/projects", json={"name": ""}, headers=h)
    body = bad.json()["error"]
    assert bad.status_code == 422 and body["code"] == "validation_error"
    assert body["details"][0]["field"] == "name"
    assert client.get("/nope").json()["error"]["code"] == "not_found"
