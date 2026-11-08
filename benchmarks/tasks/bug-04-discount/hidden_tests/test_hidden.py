import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pricing import apply_discount, total

c = TestClient(app)


def checkout(items, pct=0):
    r = c.post("/checkout", json={"items": items, "discount_percent": pct})
    return r


def test_ten_percent_off_200():
    r = checkout([{"price": 100, "qty": 2}], 10)
    assert r.status_code == 200 and r.json() == {"subtotal": 200.0, "total": 180.0}


def test_rounding_is_half_up_to_two_decimals():
    assert apply_discount(19.99, 15) == 16.99
    assert apply_discount(0.05, 50) == 0.03  # 0.025 rounds up
    assert apply_discount(100, 0) == 100.0 and apply_discount(100, 100) == 0.0


def test_total_has_no_float_noise():
    assert total([{"price": 0.1, "qty": 1}, {"price": 0.2, "qty": 1}]) == 0.3
    assert total([{"price": 19.99, "qty": 3}]) == 59.97


def test_empty_cart_is_zero():
    assert checkout([], 25).json() == {"subtotal": 0.0, "total": 0.0}


@pytest.mark.parametrize("pct", [-1, 100.5, 250])
def test_bad_percent_is_422(pct):
    assert checkout([{"price": 10, "qty": 1}], pct).status_code == 422
    with pytest.raises(ValueError):
        apply_discount(10, pct)
