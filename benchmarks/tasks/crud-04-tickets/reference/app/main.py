from typing import Literal
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
DB: dict[int, dict] = {}
_next = {"id": 1}


class Item(BaseModel):
    title: str = Field(min_length=3)
    priority: int = Field(ge=1, le=5)
    status: Literal['open', 'in_progress', 'closed'] = 'open'


def _dump(item: Item) -> dict:
    return item.model_dump(mode="json")


def reset() -> None:
    DB.clear()
    _next["id"] = 1


@app.post("/tickets", status_code=201)
def create(item: Item):
    data = _dump(item)
    item_id = _next["id"]
    _next["id"] += 1
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.get("/tickets")
def list_items(skip: int = 0, limit: int = 100):
    rows = list(DB.values())
    return rows[skip : skip + limit]


@app.get("/tickets/{item_id}")
def get_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="ticket not found")
    return DB[item_id]


@app.put("/tickets/{item_id}")
def update(item_id: int, item: Item):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="ticket not found")
    data = _dump(item)
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.delete("/tickets/{item_id}", status_code=204)
def delete(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="ticket not found")
    del DB[item_id]
    return Response(status_code=204)
