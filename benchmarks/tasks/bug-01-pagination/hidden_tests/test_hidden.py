from fastapi.testclient import TestClient

from app.main import app, paginate

c = TestClient(app)


def names(r):
    return r.json()["items"]


def test_first_page_is_the_first_ten():
    r = c.get("/items")
    assert names(r) == [f"item-{i}" for i in range(1, 11)] and r.json()["total"] == 23


def test_second_and_last_partial_page():
    assert names(c.get("/items", params={"page": 2})) == [f"item-{i}" for i in range(11, 21)]
    assert names(c.get("/items", params={"page": 3})) == ["item-21", "item-22", "item-23"]


def test_past_the_end_is_empty():
    assert names(c.get("/items", params={"page": 4})) == []


def test_custom_size():
    assert names(c.get("/items", params={"page": 2, "size": 5})) == [f"item-{i}" for i in range(6, 11)]


def test_paginate_function_directly():
    assert paginate([1, 2, 3, 4, 5], 1, 2) == [1, 2]
    assert paginate([1, 2, 3, 4, 5], 3, 2) == [5]


def test_validation_unchanged():
    assert c.get("/items", params={"page": 0}).status_code == 422
    assert c.get("/items", params={"size": 51}).status_code == 422
