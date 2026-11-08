import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)

def product(c, sku="A1", stock=5, price=2.5):
    return c.post("/products", json={"sku": sku, "name": "Thing", "price": price, "stock": stock})


def test_product_validation_and_duplicates(c):
    assert product(c).status_code == 201
    assert product(c).status_code == 409
    assert c.post("/products", json={"sku": "", "name": "x", "price": 1, "stock": 1}).status_code == 422
    assert c.post("/products", json={"sku": "B", "name": "x", "price": 0, "stock": 1}).status_code == 422
    assert c.post("/products", json={"sku": "B", "name": "x", "price": 1, "stock": -1}).status_code == 422
    assert c.get("/products/A1").json()["stock"] == 5 and c.get("/products/none").status_code == 404


def test_order_reduces_stock_and_computes_total(c):
    product(c, stock=5, price=2.5)
    r = c.post("/orders", json={"sku": "A1", "qty": 3})
    assert r.status_code == 201
    assert r.json() == {"id": 1, "sku": "A1", "qty": 3, "total": 7.5, "status": "placed"}
    assert c.get("/products/A1").json()["stock"] == 2
    assert c.get("/orders/1").json()["total"] == 7.5


def test_ordering_exactly_the_remaining_stock_is_allowed(c):
    product(c, stock=2)
    assert c.post("/orders", json={"sku": "A1", "qty": 2}).status_code == 201
    assert c.get("/products/A1").json()["stock"] == 0
    assert c.post("/orders", json={"sku": "A1", "qty": 1}).status_code == 409


def test_insufficient_stock_has_no_side_effects(c):
    product(c, stock=2)
    assert c.post("/orders", json={"sku": "A1", "qty": 3}).status_code == 409
    assert c.get("/products/A1").json()["stock"] == 2
    assert c.get("/orders/1").status_code == 404
    assert c.post("/orders", json={"sku": "A1", "qty": 1}).json()["id"] == 1


def test_unknown_sku_and_bad_qty(c):
    assert c.post("/orders", json={"sku": "nope", "qty": 1}).status_code == 404
    product(c)
    assert c.post("/orders", json={"sku": "A1", "qty": 0}).status_code == 422


def test_cancel_restores_stock_once(c):
    product(c, stock=5)
    c.post("/orders", json={"sku": "A1", "qty": 4})
    r = c.post("/orders/1/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert c.get("/products/A1").json()["stock"] == 5
    assert c.post("/orders/1/cancel").status_code == 409
    assert c.get("/products/A1").json()["stock"] == 5
    assert c.post("/orders/9/cancel").status_code == 404


def test_totals_round_to_two_decimals(c):
    product(c, stock=10, price=0.1)
    assert c.post("/orders", json={"sku": "A1", "qty": 3}).json()["total"] == 0.3
