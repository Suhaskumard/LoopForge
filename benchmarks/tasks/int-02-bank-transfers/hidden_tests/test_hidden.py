import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)

def acct(c, owner, balance):
    return c.post("/accounts", json={"owner": owner, "balance": balance}).json()["id"]


def bal(c, i):
    return c.get(f"/accounts/{i}").json()["balance"]


def xfer(c, a, b, amount):
    return c.post("/transfers", json={"from_id": a, "to_id": b, "amount": amount})


def test_open_and_validate_accounts(c):
    assert c.post("/accounts", json={"owner": "A", "balance": 10}).json() == {"id": 1, "owner": "A", "balance": 10}
    assert c.post("/accounts", json={"owner": "", "balance": 1}).status_code == 422
    assert c.post("/accounts", json={"owner": "B", "balance": -1}).status_code == 422
    assert c.get("/accounts/9").status_code == 404


def test_transfer_moves_money_and_conserves_the_total(c):
    a, b = acct(c, "A", 100), acct(c, "B", 50)
    r = xfer(c, a, b, 30.25)
    assert r.status_code == 201 and r.json() == {"id": 1, "from_id": a, "to_id": b, "amount": 30.25}
    assert bal(c, a) == 69.75 and bal(c, b) == 80.25
    assert bal(c, a) + bal(c, b) == 150


def test_overdraft_is_refused_without_side_effects(c):
    a, b = acct(c, "A", 10), acct(c, "B", 0)
    assert xfer(c, a, b, 10.01).status_code == 409
    assert (bal(c, a), bal(c, b)) == (10, 0)
    assert xfer(c, a, b, 10).status_code == 201
    assert (bal(c, a), bal(c, b)) == (0, 10)


def test_invalid_transfers(c):
    a, b = acct(c, "A", 10), acct(c, "B", 10)
    assert xfer(c, a, a, 1).status_code == 422
    assert xfer(c, a, b, 0).status_code == 422
    assert xfer(c, a, b, -5).status_code == 422
    assert xfer(c, a, 99, 1).status_code == 404
    assert xfer(c, 99, b, 1).status_code == 404
    assert (bal(c, a), bal(c, b)) == (10, 10)


def test_history_has_direction_and_order(c):
    a, b, d = acct(c, "A", 100), acct(c, "B", 100), acct(c, "D", 100)
    xfer(c, a, b, 10)
    xfer(c, b, a, 5)
    xfer(c, b, d, 1)
    h = c.get(f"/accounts/{a}/history").json()
    assert [(x["id"], x["direction"]) for x in h] == [(1, "out"), (2, "in")]
    hb = c.get(f"/accounts/{b}/history").json()
    assert [(x["id"], x["direction"]) for x in hb] == [(1, "in"), (2, "out"), (3, "out")]
    assert c.get("/accounts/99/history").status_code == 404
    assert c.get(f"/accounts/{d}/history").json()[0]["amount"] == 1


def test_rounding_keeps_two_decimals(c):
    a, b = acct(c, "A", 0.3), acct(c, "B", 0)
    xfer(c, a, b, 0.1)
    xfer(c, a, b, 0.2)
    assert bal(c, a) == 0 and bal(c, b) == 0.3
