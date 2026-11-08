from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
PRODUCTS: dict[str, dict] = {}
ORDERS: dict[int, dict] = {}
_ids = {"order": 1}


def reset() -> None:
    PRODUCTS.clear()
    ORDERS.clear()
    _ids["order"] = 1


class Product(BaseModel):
    sku: str = Field(min_length=1)
    name: str
    price: float = Field(gt=0)
    stock: int = Field(ge=0)


class OrderIn(BaseModel):
    sku: str
    qty: int = Field(ge=1)


@app.post("/products", status_code=201)
def add_product(p: Product):
    if p.sku in PRODUCTS:
        raise HTTPException(409, "duplicate sku")
    PRODUCTS[p.sku] = p.model_dump()
    return PRODUCTS[p.sku]


@app.get("/products/{sku}")
def get_product(sku: str):
    if sku not in PRODUCTS:
        raise HTTPException(404, "no such product")
    return PRODUCTS[sku]


@app.post("/orders", status_code=201)
def place(o: OrderIn):
    product = PRODUCTS.get(o.sku)
    if product is None:
        raise HTTPException(404, "no such product")
    if o.qty > product["stock"]:
        raise HTTPException(409, "insufficient stock")
    product["stock"] -= o.qty
    oid = _ids["order"]
    _ids["order"] += 1
    ORDERS[oid] = {"id": oid, "sku": o.sku, "qty": o.qty, "total": round(product["price"] * o.qty, 2), "status": "placed"}
    return ORDERS[oid]


@app.get("/orders/{oid}")
def get_order(oid: int):
    if oid not in ORDERS:
        raise HTTPException(404, "no such order")
    return ORDERS[oid]


@app.post("/orders/{oid}/cancel")
def cancel(oid: int):
    order = ORDERS.get(oid)
    if order is None:
        raise HTTPException(404, "no such order")
    if order["status"] == "cancelled":
        raise HTTPException(409, "already cancelled")
    PRODUCTS[order["sku"]]["stock"] += order["qty"]
    order["status"] = "cancelled"
    return order
