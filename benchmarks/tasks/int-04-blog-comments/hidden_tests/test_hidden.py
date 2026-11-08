import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)

def post(c, t="T"):
    return c.post("/posts", json={"title": t, "body": "b"}).json()["id"]


def comment(c, pid, text="hi", author="a"):
    return c.post(f"/posts/{pid}/comments", json={"author": author, "text": text})


def test_post_crud_basics(c):
    assert c.post("/posts", json={"title": "Hello", "body": "World"}).json() == {"id": 1, "title": "Hello", "body": "World", "comment_count": 0}
    assert c.post("/posts", json={"title": ""}).status_code == 422
    assert c.get("/posts/7").status_code == 404
    assert [p["id"] for p in c.get("/posts").json()] == [1]


def test_comments_are_global_ids_and_counted(c):
    p1, p2 = post(c), post(c)
    assert comment(c, p1).json() == {"id": 1, "post_id": p1, "author": "a", "text": "hi"}
    assert comment(c, p2).json()["id"] == 2
    assert comment(c, p1).json()["id"] == 3
    assert c.get(f"/posts/{p1}").json()["comment_count"] == 2
    assert [x["comment_count"] for x in c.get("/posts").json()] == [2, 1]
    assert [x["id"] for x in c.get(f"/posts/{p1}/comments").json()] == [1, 3]


def test_comment_validation(c):
    p = post(c)
    assert comment(c, p, text="").status_code == 422
    assert comment(c, p, text="x" * 501).status_code == 422
    assert comment(c, p, text="x" * 500).status_code == 201
    assert comment(c, p, author="").status_code == 422
    assert comment(c, 99).status_code == 404
    assert c.get("/posts/99/comments").status_code == 404


def test_deleting_a_comment_updates_the_count(c):
    p = post(c)
    cid = comment(c, p).json()["id"]
    assert c.delete(f"/comments/{cid}").status_code == 204
    assert c.get(f"/posts/{p}").json()["comment_count"] == 0
    assert c.delete(f"/comments/{cid}").status_code == 404


def test_deleting_a_post_cascades(c):
    p1, p2 = post(c), post(c)
    c1 = comment(c, p1).json()["id"]
    c2 = comment(c, p2).json()["id"]
    assert c.delete(f"/posts/{p1}").status_code == 204
    assert c.get(f"/posts/{p1}").status_code == 404
    assert c.delete(f"/comments/{c1}").status_code == 404
    assert c.get(f"/posts/{p2}/comments").json()[0]["id"] == c2
    assert c.delete("/posts/99").status_code == 404
