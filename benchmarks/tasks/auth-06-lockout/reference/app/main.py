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
from app.store import FAILED

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
