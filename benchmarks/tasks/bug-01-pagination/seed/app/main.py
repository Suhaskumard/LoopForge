from fastapi import FastAPI, Query

app = FastAPI()
ITEMS = [f"item-{i}" for i in range(1, 24)]


def paginate(items, page, size):
    start = page * size
    return items[start : start + size]


@app.get("/items")
def list_items(page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=50)):
    data = paginate(ITEMS, page, size)
    return {"page": page, "size": size, "total": len(ITEMS), "items": data}
