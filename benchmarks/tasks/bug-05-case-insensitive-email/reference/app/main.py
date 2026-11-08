from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
USERS: dict[str, dict] = {}


class NewUser(BaseModel):
    email: str
    name: str


@app.post("/users", status_code=201)
def create(u: NewUser):
    email = u.email.strip().lower()
    if email in USERS:
        raise HTTPException(status_code=409, detail="exists")
    USERS[email] = {"email": email, "name": u.name}
    return USERS[email]


@app.get("/users/{email}")
def get(email: str):
    email = email.strip().lower()
    if email not in USERS:
        raise HTTPException(status_code=404, detail="not found")
    return USERS[email]
