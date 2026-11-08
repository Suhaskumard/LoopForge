from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
DB: dict[int, dict] = {}
_next = {"id": 1}


class Item(BaseModel):
    sku: str = Field(pattern=r'^[A-Z]{3}-\d{3}$')
    name: str = Field(min_length=2)
    price: float = Field(gt=0, le=100000)


def _dump(item: Item) -> dict:
    return item.model_dump(mode="json")


def reset() -> None:
    DB.clear()
    _next["id"] = 1


@app.post("/products", status_code=201)
def create(item: Item):
    data = _dump(item)
    if any(r['sku'] == data['sku'] for r in DB.values()):
        raise HTTPException(status_code=409, detail='duplicate sku')
    item_id = _next["id"]
    _next["id"] += 1
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.get("/products")
def list_items(skip: int = 0, limit: int = 100):
    rows = list(DB.values())
    return rows[skip : skip + limit]


@app.get("/products/{item_id}")
def get_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="product not found")
    return DB[item_id]


@app.put("/products/{item_id}")
def update(item_id: int, item: Item):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="product not found")
    data = _dump(item)
    if any(r['sku'] == data['sku'] and i != item_id for i, r in DB.items()):
        raise HTTPException(status_code=409, detail='duplicate sku')
    DB[item_id] = {**data, "id": item_id}
    return DB[item_id]


@app.delete("/products/{item_id}", status_code=204)
def delete(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="product not found")
    del DB[item_id]
    return Response(status_code=204)
