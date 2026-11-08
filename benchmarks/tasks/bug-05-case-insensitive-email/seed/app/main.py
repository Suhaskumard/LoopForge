from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
USERS: dict[str, dict] = {}


class NewUser(BaseModel):
    email: str
    name: str


@app.post("/users", status_code=201)
def create(u: NewUser):
    if u.email in USERS:
        raise HTTPException(status_code=409, detail="exists")
    USERS[u.email] = {"email": u.email, "name": u.name}
    return USERS[u.email]


@app.get("/users/{email}")
def get(email: str):
    if email not in USERS:
        raise HTTPException(status_code=404, detail="not found")
    return USERS[email]
