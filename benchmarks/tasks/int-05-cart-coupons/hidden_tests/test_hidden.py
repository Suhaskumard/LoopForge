import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)

def cart(c):
    return c.post("/carts").json()["id"]


def add(c, cid, product, qty=1):
    return c.post(f"/carts/{cid}/items", json={"product": product, "qty": qty})


def coupon(c, cid, code):
    return c.post(f"/carts/{cid}/coupon", json={"code": code})


def test_new_cart_is_empty(c):
    assert c.post("/carts").json() == {"id": 1, "items": [], "subtotal": 0, "discount": 0, "total": 0, "coupon": None}
    assert c.get("/carts/9").status_code == 404


def test_items_merge_per_product_and_totals(c):
    cid = cart(c)
    add(c, cid, "apple", 3)
    add(c, cid, "bread", 1)
    r = add(c, cid, "apple", 2).json()
    assert [(i["product"], i["qty"], i["line_total"]) for i in r["items"]] == [("apple", 5, 2.5), ("bread", 1, 2.2)]
    assert r["subtotal"] == 4.7 and r["total"] == 4.7 and r["discount"] == 0


def test_invalid_item_requests(c):
    cid = cart(c)
    assert add(c, cid, "durian").status_code == 422
    assert add(c, cid, "apple", 0).status_code == 422
    assert add(c, 99, "apple").status_code == 404


def test_save10_is_ten_percent_and_rounds_half_up(c):
    cid = cart(c)
    add(c, cid, "bread", 1)
    add(c, cid, "apple", 1)  # 2.70 -> discount 0.27
    r = coupon(c, cid, "SAVE10").json()
    assert (r["subtotal"], r["discount"], r["total"], r["coupon"]) == (2.7, 0.27, 2.43, "SAVE10")
    cid2 = cart(c)
    add(c, cid2, "bread", 1)
    add(c, cid2, "apple", 1)
    add(c, cid2, "apple", 1)  # 3.20 -> 0.32
    assert coupon(c, cid2, "SAVE10").json()["discount"] == 0.32
    cid3 = cart(c)
    add(c, cid3, "apple", 1)
    add(c, cid3, "bread", 1)
    add(c, cid3, "apple", 3)  # 4.20 -> 0.42
    assert coupon(c, cid3, "SAVE10").json()["discount"] == 0.42


def test_discount_follows_later_changes(c):
    cid = cart(c)
    add(c, cid, "wine", 1)
    coupon(c, cid, "SAVE10")
    r = add(c, cid, "wine", 1).json()
    assert (r["subtotal"], r["discount"], r["total"]) == (24.0, 2.4, 21.6)
    assert c.get(f"/carts/{cid}").json()["total"] == 21.6


def test_flat5_requires_twenty_and_is_capped(c):
    cid = cart(c)
    add(c, cid, "wine", 1)
    assert coupon(c, cid, "FLAT5").status_code == 409
    assert c.get(f"/carts/{cid}").json()["coupon"] is None
    add(c, cid, "cheese", 1)  # 19.80 still below 20
    assert coupon(c, cid, "FLAT5").status_code == 409
    add(c, cid, "apple", 1)  # 20.30
    r = coupon(c, cid, "FLAT5").json()
    assert (r["subtotal"], r["discount"], r["total"]) == (20.3, 5.0, 15.3)


def test_flat5_at_exactly_twenty(c):
    cid = cart(c)
    add(c, cid, "cheese", 2)  # 15.60
    add(c, cid, "bread", 2)  # + 4.40 = 20.00
    r = coupon(c, cid, "FLAT5").json()
    assert (r["subtotal"], r["total"]) == (20.0, 15.0)


def test_one_coupon_only_and_unknown_codes(c):
    cid = cart(c)
    add(c, cid, "wine", 2)
    assert coupon(c, cid, "NOPE").status_code == 422
    assert coupon(c, cid, "SAVE10").status_code == 200
    assert coupon(c, cid, "FLAT5").status_code == 409
    assert coupon(c, cid, "SAVE10").status_code == 409
    assert coupon(c, 99, "SAVE10").status_code == 404
    assert c.get(f"/carts/{cid}").json()["coupon"] == "SAVE10"
