import pytest
from fastapi.testclient import TestClient

from app.main import USERS, app

c = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    USERS.clear()


def test_email_is_normalised_on_create():
    r = c.post("/users", json={"email": "  Ann@Example.COM ", "name": "Ann"})
    assert r.status_code == 201 and r.json() == {"email": "ann@example.com", "name": "Ann"}


def test_duplicates_ignore_case_and_whitespace():
    assert c.post("/users", json={"email": "ann@example.com", "name": "A"}).status_code == 201
    assert c.post("/users", json={"email": "ANN@example.com", "name": "B"}).status_code == 409
    assert c.post("/users", json={"email": " ann@example.com ", "name": "C"}).status_code == 409
    assert len(USERS) == 1


def test_lookup_is_case_insensitive():
    c.post("/users", json={"email": "ann@example.com", "name": "Ann"})
    assert c.get("/users/ANN@Example.com").json()["name"] == "Ann"


def test_unknown_is_404():
    assert c.get("/users/ghost@example.com").status_code == 404


def test_distinct_users_still_work():
    assert c.post("/users", json={"email": "a@x.com", "name": "A"}).status_code == 201
    assert c.post("/users", json={"email": "b@x.com", "name": "B"}).status_code == 201
