import pytest
from fastapi.testclient import TestClient

from app.main import NOTES, app

c = TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    NOTES.clear()
    NOTES.update({1: {"id": 1, "text": "first"}, 2: {"id": 2, "text": "second"}})


def ids():
    return [n["id"] for n in c.get("/notes").json()]


def test_delete_really_removes():
    assert c.delete("/notes/1").status_code == 204
    assert ids() == [2]


def test_second_delete_is_404():
    c.delete("/notes/1")
    assert c.delete("/notes/1").status_code == 404


def test_unknown_id_is_404_and_nothing_changes():
    assert c.delete("/notes/99").status_code == 404
    assert ids() == [1, 2]


def test_remaining_ids_unchanged_and_new_id_is_max_plus_one():
    c.delete("/notes/1")
    r = c.post("/notes", json={"text": "third"})
    assert r.status_code == 201 and r.json() == {"id": 3, "text": "third"}
    assert ids() == [2, 3]


def test_delete_the_highest_then_add():
    c.delete("/notes/2")
    assert c.post("/notes", json={"text": "x"}).json()["id"] == 2
