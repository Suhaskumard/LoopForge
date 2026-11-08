from datetime import date
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
DB: dict[int, dict] = {}
_next = {"id": 1}


class Item(BaseModel):
    title: str = Field(min_length=1)
    capacity: int = Field(ge=1, le=1000)
    starts_on: date = Field()


def _dump(item: Item) -> dict:
    return item.model_dump(mode="json")


def reset() -> None:
    DB.clear()
    _next["id"] = 1


@app.post("/events", status_code=201)
def create(item: Item):
    data = _dump(item)
    item_id = _next["id"]
    _next["id"] += 1
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.get("/events")
def list_items(skip: int = 0, limit: int = 100, min_capacity: int | None = None):
    rows = list(DB.values())
    if min_capacity is not None:
        rows = [r for r in rows if r['capacity'] >= min_capacity]
    return rows[skip : skip + limit]


@app.get("/events/{item_id}")
def get_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="event not found")
    return DB[item_id]


@app.put("/events/{item_id}")
def update(item_id: int, item: Item):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="event not found")
    data = _dump(item)
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.delete("/events/{item_id}", status_code=204)
def delete(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="event not found")
    del DB[item_id]
    return Response(status_code=204)
