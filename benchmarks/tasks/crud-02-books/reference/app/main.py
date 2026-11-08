from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
DB: dict[int, dict] = {}
_next = {"id": 1}


class Item(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    isbn: str = Field(pattern=r'^\d{13}$')
    price: float = Field(gt=0)
    stock: int = Field(ge=0)


def _dump(item: Item) -> dict:
    return item.model_dump(mode="json")


def reset() -> None:
    DB.clear()
    _next["id"] = 1


@app.post("/books", status_code=201)
def create(item: Item):
    data = _dump(item)
    if any(r['isbn'] == data['isbn'] for r in DB.values()):
        raise HTTPException(status_code=409, detail='duplicate isbn')
    item_id = _next["id"]
    _next["id"] += 1
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.get("/books")
def list_items(skip: int = 0, limit: int = 100):
    rows = list(DB.values())
    return rows[skip : skip + limit]


@app.get("/books/{item_id}")
def get_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="book not found")
    return DB[item_id]


@app.put("/books/{item_id}")
def update(item_id: int, item: Item):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="book not found")
    data = _dump(item)
    if any(r['isbn'] == data['isbn'] and i != item_id for i, r in DB.items()):
        raise HTTPException(status_code=409, detail='duplicate isbn')
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.delete("/books/{item_id}", status_code=204)
def delete(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="book not found")
    del DB[item_id]
    return Response(status_code=204)
