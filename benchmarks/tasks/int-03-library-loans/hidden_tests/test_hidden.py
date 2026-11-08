import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)

def book(c, t="B"):
    return c.post("/books", json={"title": t}).json()["id"]


def member(c, n="M"):
    return c.post("/members", json={"name": n}).json()["id"]


def lend(c, b, m):
    return c.post("/loans", json={"book_id": b, "member_id": m})


def test_creation_and_validation(c):
    assert c.post("/books", json={"title": "Dune"}).json() == {"id": 1, "title": "Dune", "available": True}
    assert c.post("/books", json={"title": ""}).status_code == 422
    assert c.post("/members", json={"name": ""}).status_code == 422
    assert c.get("/books/5").status_code == 404


def test_lending_marks_the_book_unavailable(c):
    b, m = book(c), member(c)
    r = lend(c, b, m)
    assert r.status_code == 201 and r.json() == {"id": 1, "book_id": b, "member_id": m, "returned": False}
    assert c.get(f"/books/{b}").json()["available"] is False


def test_a_book_cannot_be_lent_twice(c):
    b, m1, m2 = book(c), member(c), member(c)
    lend(c, b, m1)
    assert lend(c, b, m2).status_code == 409


def test_unknown_book_or_member(c):
    b, m = book(c), member(c)
    assert lend(c, 99, m).status_code == 404
    assert lend(c, b, 99).status_code == 404
    assert c.get(f"/books/{b}").json()["available"] is True


def test_three_loan_limit_and_return_frees_a_slot(c):
    m = member(c)
    books = [book(c, f"B{i}") for i in range(4)]
    loans = [lend(c, b, m).json()["id"] for b in books[:3]]
    assert lend(c, books[3], m).status_code == 409
    assert c.get(f"/books/{books[3]}").json()["available"] is True
    assert c.post(f"/loans/{loans[0]}/return").status_code == 200
    assert lend(c, books[3], m).status_code == 201


def test_return_rules(c):
    b, m = book(c), member(c)
    lid = lend(c, b, m).json()["id"]
    r = c.post(f"/loans/{lid}/return")
    assert r.json()["returned"] is True and c.get(f"/books/{b}").json()["available"] is True
    assert c.post(f"/loans/{lid}/return").status_code == 409
    assert c.post("/loans/99/return").status_code == 404


def test_member_loans_list_only_unreturned(c):
    m = member(c)
    b1, b2 = book(c), book(c)
    l1 = lend(c, b1, m).json()["id"]
    lend(c, b2, m)
    c.post(f"/loans/{l1}/return")
    assert [x["book_id"] for x in c.get(f"/members/{m}/loans").json()] == [b2]
    assert c.get("/members/99/loans").status_code == 404


def test_returned_book_can_go_to_someone_else(c):
    b, m1, m2 = book(c), member(c), member(c)
    lid = lend(c, b, m1).json()["id"]
    c.post(f"/loans/{lid}/return")
    assert lend(c, b, m2).status_code == 201
