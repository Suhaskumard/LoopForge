from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pricing import apply_discount, total

app = FastAPI()


class Item(BaseModel):
    price: float
    qty: int


class Cart(BaseModel):
    items: list[Item]
    discount_percent: float = 0


@app.post("/checkout")
def checkout(cart: Cart):
    raw = total([i.model_dump() for i in cart.items])
    try:
        final = apply_discount(raw, cart.discount_percent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"subtotal": raw, "total": final}
