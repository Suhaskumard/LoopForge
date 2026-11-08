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
import re


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
    if not re.search(r"\d", pw):
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
