from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
DB: dict[int, dict] = {}
_next = {"id": 1}


class Item(BaseModel):
    name: str = Field(min_length=1)
    grade: int = Field(ge=0, le=100)
    email: str = Field(pattern=r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$')


def _dump(item: Item) -> dict:
    return item.model_dump(mode="json")


def reset() -> None:
    DB.clear()
    _next["id"] = 1


@app.post("/students", status_code=201)
def create(item: Item):
    data = _dump(item)
    if any(r['email'] == data['email'] for r in DB.values()):
        raise HTTPException(status_code=409, detail='duplicate email')
    item_id = _next["id"]
    _next["id"] += 1
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.get("/students")
def list_items(skip: int = 0, limit: int = 100):
    rows = list(DB.values())
    return rows[skip : skip + limit]


@app.get("/students/{item_id}")
def get_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="student not found")
    return DB[item_id]


@app.put("/students/{item_id}")
def update(item_id: int, item: Item):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="student not found")
    data = _dump(item)
    if any(r['email'] == data['email'] and i != item_id for i, r in DB.items()):
        raise HTTPException(status_code=409, detail='duplicate email')
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.delete("/students/{item_id}", status_code=204)
def delete(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="student not found")
    del DB[item_id]
    return Response(status_code=204)
