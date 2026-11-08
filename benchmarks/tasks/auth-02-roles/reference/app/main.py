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
