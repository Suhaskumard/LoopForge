import secrets

from fastapi import Depends, FastAPI, Header, HTTPException

app = FastAPI()
API_KEY = "sk-bench-12345"


def require_key(x_api_key: str | None = Header(default=None)):
    if x_api_key is None or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/secret", dependencies=[Depends(require_key)])
def secret():
    return {"data": "classified"}


@app.get("/public")
def public():
    return {"data": "hello"}
