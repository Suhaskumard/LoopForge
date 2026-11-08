from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
ACCOUNTS: dict[int, dict] = {}
TRANSFERS: list[dict] = []
_ids = {"account": 1, "transfer": 1}


def reset() -> None:
    ACCOUNTS.clear()
    TRANSFERS.clear()
    _ids.update(account=1, transfer=1)


class AccountIn(BaseModel):
    owner: str = Field(min_length=1)
    balance: float = Field(ge=0)


class TransferIn(BaseModel):
    from_id: int
    to_id: int
    amount: float = Field(gt=0)


@app.post("/accounts", status_code=201)
def open_account(a: AccountIn):
    aid = _ids["account"]
    _ids["account"] += 1
    ACCOUNTS[aid] = {"id": aid, "owner": a.owner, "balance": round(a.balance, 2)}
    return ACCOUNTS[aid]


@app.get("/accounts/{aid}")
def get_account(aid: int):
    if aid not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    return ACCOUNTS[aid]


@app.post("/transfers", status_code=201)
def transfer(t: TransferIn):
    if t.from_id == t.to_id:
        raise HTTPException(422, "cannot transfer to the same account")
    src, dst = ACCOUNTS.get(t.from_id), ACCOUNTS.get(t.to_id)
    if src is None or dst is None:
        raise HTTPException(404, "no such account")
    if t.amount > src["balance"]:
        raise HTTPException(409, "insufficient funds")
    src["balance"] = round(src["balance"] - t.amount, 2)
    dst["balance"] = round(dst["balance"] + t.amount, 2)
    tid = _ids["transfer"]
    _ids["transfer"] += 1
    TRANSFERS.append({"id": tid, "from_id": t.from_id, "to_id": t.to_id, "amount": t.amount})
    return TRANSFERS[-1]


@app.get("/accounts/{aid}/history")
def history(aid: int):
    if aid not in ACCOUNTS:
        raise HTTPException(404, "no such account")
    return [{**t, "direction": "out" if t["from_id"] == aid else "in"} for t in TRANSFERS if aid in (t["from_id"], t["to_id"])]
