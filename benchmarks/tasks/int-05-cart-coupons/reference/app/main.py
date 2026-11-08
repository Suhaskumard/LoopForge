from decimal import ROUND_HALF_UP, Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
CATALOGUE = {"apple": Decimal("0.50"), "bread": Decimal("2.20"), "cheese": Decimal("7.80"), "wine": Decimal("12.00")}
CARTS: dict[int, dict] = {}
_ids = {"cart": 1}
CENT = Decimal("0.01")


def reset() -> None:
    CARTS.clear()
    _ids["cart"] = 1


class ItemIn(BaseModel):
    product: str
    qty: int = Field(ge=1)


class CouponIn(BaseModel):
    code: str


def money(x: Decimal) -> float:
    return float(x.quantize(CENT, rounding=ROUND_HALF_UP))


def view(cart: dict) -> dict:
    lines = [
        {"product": p, "qty": q, "unit_price": float(CATALOGUE[p]), "line_total": money(CATALOGUE[p] * q)}
        for p, q in cart["lines"].items()
    ]
    subtotal = sum((CATALOGUE[p] * q for p, q in cart["lines"].items()), Decimal(0))
    code = cart["coupon"]
    discount = Decimal(0)
    if code == "SAVE10":
        discount = subtotal * Decimal("0.10")
    elif code == "FLAT5":
        discount = min(Decimal(5), subtotal)
    discount = discount.quantize(CENT, rounding=ROUND_HALF_UP)
    total = max(subtotal.quantize(CENT, rounding=ROUND_HALF_UP) - discount, Decimal(0))
    return {"id": cart["id"], "items": lines, "subtotal": money(subtotal), "discount": float(discount), "total": float(total), "coupon": code}


def get_cart(cid: int) -> dict:
    if cid not in CARTS:
        raise HTTPException(404, "no such cart")
    return CARTS[cid]


@app.post("/carts", status_code=201)
def new_cart():
    i = _ids["cart"]
    _ids["cart"] += 1
    CARTS[i] = {"id": i, "lines": {}, "coupon": None}
    return view(CARTS[i])


@app.post("/carts/{cid}/items")
def add_item(cid: int, item: ItemIn):
    cart = get_cart(cid)
    if item.product not in CATALOGUE:
        raise HTTPException(422, "unknown product")
    cart["lines"][item.product] = cart["lines"].get(item.product, 0) + item.qty
    return view(cart)


@app.post("/carts/{cid}/coupon")
def apply_coupon(cid: int, c: CouponIn):
    cart = get_cart(cid)
    if c.code not in ("SAVE10", "FLAT5"):
        raise HTTPException(422, "unknown coupon")
    if cart["coupon"] is not None:
        raise HTTPException(409, "coupon already applied")
    if c.code == "FLAT5":
        subtotal = sum((CATALOGUE[p] * q for p, q in cart["lines"].items()), Decimal(0))
        if subtotal < 20:
            raise HTTPException(409, "FLAT5 needs a subtotal of at least 20.00")
    cart["coupon"] = c.code
    return view(cart)


@app.get("/carts/{cid}")
def read_cart(cid: int):
    return view(get_cart(cid))
