import time

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.config import ALGORITHM, SECRET
from app.store import USERS

app = FastAPI()
bearer = HTTPBearer(auto_error=False)
import uuid


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
