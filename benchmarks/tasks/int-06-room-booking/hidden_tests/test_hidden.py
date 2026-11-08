import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.main import app


@pytest.fixture()
def c():
    m.reset()
    return TestClient(app)

def room(c, name="Big", cap=10):
    return c.post("/rooms", json={"name": name, "capacity": cap}).json()["id"]


def book(c, rid, start, end, n=2):
    return c.post("/bookings", json={"room_id": rid, "start": start, "end": end, "attendees": n})


D = "2030-01-01T"


def test_rooms(c):
    assert c.post("/rooms", json={"name": "A", "capacity": 4}).json() == {"id": 1, "name": "A", "capacity": 4}
    assert c.post("/rooms", json={"name": "A", "capacity": 4}).status_code == 409
    assert c.post("/rooms", json={"name": "", "capacity": 4}).status_code == 422
    assert c.post("/rooms", json={"name": "B", "capacity": 0}).status_code == 422


def test_booking_is_confirmed_and_echoed(c):
    rid = room(c)
    r = book(c, rid, D + "09:00", D + "10:00", 3)
    assert r.status_code == 201
    assert r.json() == {"id": 1, "room_id": rid, "start": D + "09:00", "end": D + "10:00", "attendees": 3, "status": "confirmed"}


def test_validation(c):
    rid = room(c, cap=5)
    assert book(c, 99, D + "09:00", D + "10:00").status_code == 404
    assert book(c, rid, D + "10:00", D + "09:00").status_code == 422
    assert book(c, rid, D + "10:00", D + "10:00").status_code == 422
    assert book(c, rid, "2030-01-01 09:00", D + "10:00").status_code == 422
    assert book(c, rid, "2030-02-30T09:00", "2030-02-30T10:00").status_code == 422
    assert book(c, rid, D + "09:00", D + "10:00", 6).status_code == 422
    assert book(c, rid, D + "09:00", D + "10:00", 5).status_code == 201


def test_overlaps_conflict_but_adjacent_slots_do_not(c):
    rid = room(c)
    assert book(c, rid, D + "09:00", D + "10:00").status_code == 201
    assert book(c, rid, D + "09:30", D + "10:30").status_code == 409
    assert book(c, rid, D + "08:00", D + "09:30").status_code == 409
    assert book(c, rid, D + "08:00", D + "11:00").status_code == 409  # fully contains
    assert book(c, rid, D + "09:15", D + "09:45").status_code == 409  # fully inside
    assert book(c, rid, D + "10:00", D + "11:00").status_code == 201  # starts when the first ends
    assert book(c, rid, D + "08:00", D + "09:00").status_code == 201  # ends when the first starts


def test_other_rooms_are_independent(c):
    a, b = room(c, "A"), room(c, "B")
    book(c, a, D + "09:00", D + "10:00")
    assert book(c, b, D + "09:00", D + "10:00").status_code == 201


def test_cancel_frees_the_slot(c):
    rid = room(c)
    first = book(c, rid, D + "09:00", D + "10:00").json()["id"]
    r = c.delete(f"/bookings/{first}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert book(c, rid, D + "09:00", D + "10:00").status_code == 201
    assert c.delete(f"/bookings/{first}").status_code == 404
    assert c.delete("/bookings/99").status_code == 404


def test_room_listing_is_sorted_confirmed_only(c):
    rid = room(c)
    late = book(c, rid, D + "15:00", D + "16:00").json()["id"]
    book(c, rid, D + "09:00", D + "10:00")
    cancelled = book(c, rid, D + "11:00", D + "12:00").json()["id"]
    c.delete(f"/bookings/{cancelled}")
    rows = c.get(f"/rooms/{rid}/bookings").json()
    assert [r["start"] for r in rows] == [D + "09:00", D + "15:00"]
    assert late in [r["id"] for r in rows] and cancelled not in [r["id"] for r in rows]
    assert c.get("/rooms/99/bookings").status_code == 404
