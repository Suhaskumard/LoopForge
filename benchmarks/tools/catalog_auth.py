"""Authentication tasks (JWT, hashing, roles, expiry, refresh, lockout).

Every contract names the exact module attributes the hidden tests rely on (e.g. `app.config.SECRET`)
because the tests are hidden: the requirement text IS the interface specification.
"""

from typing import Any

COMMON = """Use PyJWT (`import jwt`) with HS256 and bcrypt (`import bcrypt`) for password hashing.
Create `app/config.py` defining `SECRET = "benchmark-secret-key-0123456789abcdef"` and `ALGORITHM = "HS256"`.
Users are stored in memory in a dict `app.store.USERS` keyed by lower-cased email; each value is a dict
with at least `email` and `password_hash` (a bcrypt hash, never the plaintext password).
The app entry point is `app.main:app`. Include unit tests (pytest)."""

PREAMBLE = '''import time

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
'''

BASE_APP = '''import time

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.config import ALGORITHM, SECRET
from app.store import USERS

app = FastAPI()
bearer = HTTPBearer(auto_error=False)
'''

STORE = "USERS: dict[str, dict] = {}\n"
CONFIG = 'SECRET = "benchmark-secret-key-0123456789abcdef"\nALGORITHM = "HS256"\n'


def _files(main: str, store: str = STORE) -> dict[str, str]:
    return {"app/__init__.py": "", "app/config.py": CONFIG, "app/store.py": store, "app/main.py": main}


def task_basic() -> dict[str, Any]:
    main = BASE_APP + '''

class Creds(BaseModel):
    email: str
    password: str = Field(min_length=8)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "missing token")
    try:
        claims = jwt.decode(cred.credentials, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token") from None
    user = USERS.get(claims.get("sub", ""))
    if user is None:
        raise HTTPException(401, "unknown user")
    return user


@app.post("/auth/register", status_code=201)
def register(c: Creds):
    key = c.email.lower()
    if key in USERS:
        raise HTTPException(409, "email taken")
    h = bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode()
    USERS[key] = {"email": key, "password_hash": h}
    return {"email": key}


@app.post("/auth/login")
def login(c: Creds):
    user = USERS.get(c.email.lower())
    if user is None or not bcrypt.checkpw(c.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "bad credentials")
    token = jwt.encode({"sub": user["email"], "exp": int(time.time()) + 900}, SECRET, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"]}
'''
    test = PREAMBLE + '''

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
'''
    req = f"""Build a FastAPI JWT authentication service.
{COMMON}

Endpoints:
- `POST /auth/register` with JSON `{{"email", "password"}}` -> 201 `{{"email": <lower-cased email>}}`; password must be at least 8 characters (else 422); emails are case-insensitive and unique (duplicate -> 409).
- `POST /auth/login` with the same JSON -> 200 `{{"access_token": <JWT>, "token_type": "bearer"}}`; wrong password or unknown user -> 401. The JWT's `sub` claim is the lower-cased email and it has an `exp` claim at most 1 hour ahead.
- `GET /me` with header `Authorization: Bearer <token>` -> 200 `{{"email": ...}}`; missing, malformed, forged or expired token -> 401."""
    return {
        "id": "auth-01-jwt-basic",
        "category": "authentication",
        "difficulty": "medium",
        "requirement": req,
        "acceptance_criteria": [
            "Register, login and /me work end to end with a JWT",
            "Passwords are stored as bcrypt hashes",
            "Invalid or forged tokens return 401",
            "Duplicate email returns 409",
        ],
        "reference": _files(main),
        "hidden_test": test,
        "seed": None,
    }


def task_roles() -> dict[str, Any]:
    main = BASE_APP + '''

class Creds(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str = "user"


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "missing token")
    try:
        claims = jwt.decode(cred.credentials, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token") from None
    user = USERS.get(claims.get("sub", ""))
    if user is None:
        raise HTTPException(401, "unknown user")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "admin only")
    return user


@app.post("/auth/register", status_code=201)
def register(c: Creds):
    if c.role not in ("user", "admin"):
        raise HTTPException(422, "bad role")
    key = c.email.lower()
    if key in USERS:
        raise HTTPException(409, "email taken")
    h = bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode()
    USERS[key] = {"email": key, "password_hash": h, "role": c.role}
    return {"email": key, "role": c.role}


@app.post("/auth/login")
def login(c: Creds):
    user = USERS.get(c.email.lower())
    if user is None or not bcrypt.checkpw(c.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "bad credentials")
    token = jwt.encode({"sub": user["email"], "role": user["role"], "exp": int(time.time()) + 900}, SECRET, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/profile")
def profile(user: dict = Depends(current_user)):
    return {"email": user["email"], "role": user["role"]}


@app.get("/admin/users")
def admin_users(_: dict = Depends(require_admin)):
    return sorted(USERS)
'''
    test = PREAMBLE + '''

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
'''
    req = f"""Build a FastAPI JWT service with role-based access control.
{COMMON}
Each user dict also has a `role` ("user" or "admin").

Endpoints:
- `POST /auth/register` JSON `{{"email", "password" (min 8 chars), "role" (optional, default "user")}}` -> 201 `{{"email", "role"}}`; a role other than user/admin -> 422; duplicate email (case-insensitive) -> 409.
- `POST /auth/login` JSON `{{"email", "password"}}` -> 200 `{{"access_token", "token_type": "bearer"}}`; bad credentials -> 401.
- `GET /profile` (any logged-in user) -> 200 `{{"email", "role"}}`.
- `GET /admin/users` (admin only) -> 200 sorted list of all registered emails. No token or invalid token -> 401; a valid token for a non-admin -> 403.
The role must be taken from the stored user record, NOT trusted from the token, so a forged token claiming `admin` for a normal user gets 403."""
    return {
        "id": "auth-02-roles",
        "category": "authentication",
        "difficulty": "medium",
        "requirement": req,
        "acceptance_criteria": [
            "Admin-only endpoint returns 403 to normal users and 401 to anonymous callers",
            "Role is read from the stored user, not from the token",
            "Invalid roles are rejected",
        ],
        "reference": _files(main),
        "hidden_test": test,
        "seed": None,
    }


def task_password_policy() -> dict[str, Any]:
    main = BASE_APP + '''import re


class Creds(BaseModel):
    email: str
    password: str


def problems(pw: str) -> list[str]:
    out = []
    if len(pw) < 10:
        out.append("too_short")
    if not re.search(r"[A-Z]", pw):
        out.append("no_upper")
    if not re.search(r"[a-z]", pw):
        out.append("no_lower")
    if not re.search(r"\\d", pw):
        out.append("no_digit")
    return out


@app.post("/auth/register", status_code=201)
def register(c: Creds):
    bad = problems(c.password)
    if bad:
        raise HTTPException(422, {"violations": bad})
    key = c.email.lower()
    if key in USERS:
        raise HTTPException(409, "email taken")
    USERS[key] = {"email": key, "password_hash": bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode()}
    return {"email": key}


@app.post("/auth/login")
def login(c: Creds):
    user = USERS.get(c.email.lower())
    if user is None or not bcrypt.checkpw(c.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "bad credentials")
    return {"access_token": jwt.encode({"sub": user["email"], "exp": int(time.time()) + 900}, SECRET, algorithm=ALGORITHM), "token_type": "bearer"}
'''
    test = PREAMBLE + '''

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
'''
    req = f"""Build a FastAPI registration/login service with a password policy.
{COMMON}

- `POST /auth/register` JSON `{{"email", "password"}}`. A password must have: at least 10 characters, an uppercase letter, a lowercase letter and a digit. If any rule is broken respond 422 with JSON body `{{"detail": {{"violations": [<codes>]}}}}` listing EVERY broken rule using the codes `too_short`, `no_upper`, `no_lower`, `no_digit`. Valid -> 201 `{{"email": <lower-cased>}}`; duplicate email (case-insensitive) -> 409.
- `POST /auth/login` JSON `{{"email", "password"}}` -> 200 `{{"access_token", "token_type": "bearer"}}` or 401."""
    return {
        "id": "auth-03-password-policy",
        "category": "authentication",
        "difficulty": "medium",
        "requirement": req,
        "acceptance_criteria": [
            "Every broken password rule is reported by code",
            "Valid passwords register and can log in",
            "Passwords are stored as bcrypt hashes",
        ],
        "reference": _files(main),
        "hidden_test": test,
        "seed": None,
    }


def task_expiry() -> dict[str, Any]:
    main = BASE_APP + '''
TOKEN_TTL_SECONDS = 600


class Creds(BaseModel):
    email: str
    password: str = Field(min_length=8)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "missing token")
    try:
        claims = jwt.decode(cred.credentials, SECRET, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token") from None
    user = USERS.get(claims["sub"])
    if user is None:
        raise HTTPException(401, "unknown user")
    return user


@app.post("/auth/register", status_code=201)
def register(c: Creds):
    key = c.email.lower()
    if key in USERS:
        raise HTTPException(409, "email taken")
    USERS[key] = {"email": key, "password_hash": bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode()}
    return {"email": key}


@app.post("/auth/login")
def login(c: Creds):
    user = USERS.get(c.email.lower())
    if user is None or not bcrypt.checkpw(c.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "bad credentials")
    now = int(time.time())
    token = jwt.encode({"sub": user["email"], "iat": now, "exp": now + TOKEN_TTL_SECONDS}, SECRET, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS}


@app.get("/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"]}
'''
    test = PREAMBLE + '''

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
'''
    req = f"""Build a FastAPI JWT service whose access tokens expire.
{COMMON}

- `POST /auth/register` JSON `{{"email", "password" (min 8)}}` -> 201 `{{"email"}}` (lower-cased); duplicate -> 409.
- `POST /auth/login` -> 200 `{{"access_token", "token_type": "bearer", "expires_in": 600}}`. The JWT contains `sub` (lower-cased email), `iat` and `exp` where `exp - iat == 600` seconds. Bad credentials -> 401.
- `GET /me` with a bearer token -> 200 `{{"email"}}`. Return 401 for: no token, malformed token, wrong signature, EXPIRED token, a token with no `exp` claim, an unsigned (`alg: none`) token, and a token whose user no longer exists."""
    return {
        "id": "auth-04-token-expiry",
        "category": "authentication",
        "difficulty": "hard",
        "requirement": req,
        "acceptance_criteria": [
            "Tokens expire after 600 seconds and expired tokens are rejected",
            "Tokens without exp or with alg none are rejected",
            "Tokens of deleted users are rejected",
        ],
        "reference": _files(main),
        "hidden_test": test,
        "seed": None,
    }


def task_refresh() -> dict[str, Any]:
    main = BASE_APP + '''import uuid


class Creds(BaseModel):
    email: str
    password: str = Field(min_length=8)


class Refresh(BaseModel):
    refresh_token: str


def issue(email: str, kind: str, ttl: int) -> str:
    return jwt.encode({"sub": email, "typ": kind, "jti": uuid.uuid4().hex, "exp": int(time.time()) + ttl}, SECRET, algorithm=ALGORITHM)


def decode(token: str, kind: str) -> dict:
    try:
        claims = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token") from None
    if claims.get("typ") != kind or claims["sub"] not in USERS:
        raise HTTPException(401, "wrong token type")
    return claims


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "missing token")
    return USERS[decode(cred.credentials, "access")["sub"]]


@app.post("/auth/register", status_code=201)
def register(c: Creds):
    key = c.email.lower()
    if key in USERS:
        raise HTTPException(409, "email taken")
    USERS[key] = {"email": key, "password_hash": bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode()}
    return {"email": key}


@app.post("/auth/login")
def login(c: Creds):
    user = USERS.get(c.email.lower())
    if user is None or not bcrypt.checkpw(c.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "bad credentials")
    return {"access_token": issue(user["email"], "access", 900), "refresh_token": issue(user["email"], "refresh", 86400), "token_type": "bearer"}


@app.post("/auth/refresh")
def refresh(body: Refresh):
    claims = decode(body.refresh_token, "refresh")
    return {"access_token": issue(claims["sub"], "access", 900), "token_type": "bearer"}


@app.get("/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"]}
'''
    test = PREAMBLE + '''

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
'''
    req = f"""Build a FastAPI JWT service with access and refresh tokens.
{COMMON}

- `POST /auth/register` JSON `{{"email", "password" (min 8)}}` -> 201; duplicate (case-insensitive) -> 409.
- `POST /auth/login` -> 200 `{{"access_token", "refresh_token", "token_type": "bearer"}}`. Both are JWTs with claims `sub` and `exp` plus a claim `typ` that is `"access"` or `"refresh"`; the refresh token lives longer than the access token. Bad credentials -> 401.
- `POST /auth/refresh` JSON `{{"refresh_token"}}` -> 200 `{{"access_token", "token_type": "bearer"}}`. Anything that is not a valid, unexpired REFRESH token (including an access token) -> 401.
- `GET /me` with `Authorization: Bearer <access token>` -> 200 `{{"email"}}`. A refresh token used here must be rejected with 401."""
    return {
        "id": "auth-05-refresh-tokens",
        "category": "authentication",
        "difficulty": "hard",
        "requirement": req,
        "acceptance_criteria": [
            "Refresh tokens mint new access tokens",
            "Token types cannot be swapped (access vs refresh)",
            "Expired and garbage refresh tokens are rejected",
        ],
        "reference": _files(main),
        "hidden_test": test,
        "seed": None,
    }


def task_lockout() -> dict[str, Any]:
    store = STORE + "FAILED: dict[str, int] = {}\n"
    main = BASE_APP + '''from app.store import FAILED

MAX_FAILURES = 3


class Creds(BaseModel):
    email: str
    password: str = Field(min_length=8)


@app.post("/auth/register", status_code=201)
def register(c: Creds):
    key = c.email.lower()
    if key in USERS:
        raise HTTPException(409, "email taken")
    USERS[key] = {"email": key, "password_hash": bcrypt.hashpw(c.password.encode(), bcrypt.gensalt()).decode()}
    return {"email": key}


@app.post("/auth/login")
def login(c: Creds):
    key = c.email.lower()
    if FAILED.get(key, 0) >= MAX_FAILURES:
        raise HTTPException(429, "too many failed attempts")
    user = USERS.get(key)
    if user is None or not bcrypt.checkpw(c.password.encode(), user["password_hash"].encode()):
        FAILED[key] = FAILED.get(key, 0) + 1
        raise HTTPException(401, "bad credentials")
    FAILED.pop(key, None)
    return {"access_token": jwt.encode({"sub": key, "exp": int(time.time()) + 900}, SECRET, algorithm=ALGORITHM), "token_type": "bearer"}
'''
    test = PREAMBLE + '''

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
'''
    req = f"""Build a FastAPI login service with brute-force protection.
{COMMON}
Also create `app.store.FAILED`, a dict mapping lower-cased email to the number of consecutive failed logins.

- `POST /auth/register` JSON `{{"email", "password" (min 8)}}` -> 201; duplicate -> 409.
- `POST /auth/login` JSON `{{"email", "password"}}` -> 200 `{{"access_token", "token_type": "bearer"}}` or 401 for bad credentials.
- After 3 consecutive failed logins for an email (including emails that do not exist, compared case-insensitively) every further login for that email returns 429 - even with the correct password. A successful login before reaching 3 failures resets the counter. Other accounts are unaffected."""
    return {
        "id": "auth-06-lockout",
        "category": "authentication",
        "difficulty": "hard",
        "requirement": req,
        "acceptance_criteria": [
            "Three failed logins lock the account with 429",
            "A successful login resets the counter",
            "Lockout is per account and case-insensitive",
        ],
        "reference": _files(main, store),
        "hidden_test": test,
        "seed": None,
    }


def tasks() -> list[dict[str, Any]]:
    return [
        task_basic(),
        task_roles(),
        task_password_policy(),
        task_expiry(),
        task_refresh(),
        task_lockout(),
    ]
