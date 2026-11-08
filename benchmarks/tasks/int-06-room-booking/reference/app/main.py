from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
ROOMS: dict[int, dict] = {}
BOOKINGS: dict[int, dict] = {}
_ids = {"room": 1, "booking": 1}
FMT = "%Y-%m-%dT%H:%M"


def reset() -> None:
    ROOMS.clear()
    BOOKINGS.clear()
    _ids.update(room=1, booking=1)


class RoomIn(BaseModel):
    name: str = Field(min_length=1)
    capacity: int = Field(ge=1)


class BookingIn(BaseModel):
    room_id: int
    start: str
    end: str
    attendees: int = Field(ge=1)


def parse(value: str) -> datetime:
    try:
        return datetime.strptime(value, FMT)
    except ValueError:
        raise HTTPException(422, "bad datetime") from None


@app.post("/rooms", status_code=201)
def add_room(r: RoomIn):
    if any(x["name"] == r.name for x in ROOMS.values()):
        raise HTTPException(409, "duplicate room name")
    i = _ids["room"]
    _ids["room"] += 1
    ROOMS[i] = {"id": i, "name": r.name, "capacity": r.capacity}
    return ROOMS[i]


@app.post("/bookings", status_code=201)
def book(b: BookingIn):
    room = ROOMS.get(b.room_id)
    if room is None:
        raise HTTPException(404, "no such room")
    start, end = parse(b.start), parse(b.end)
    if end <= start:
        raise HTTPException(422, "end must be after start")
    if b.attendees > room["capacity"]:
        raise HTTPException(422, "over capacity")
    for other in BOOKINGS.values():
        if other["room_id"] == b.room_id and other["status"] == "confirmed":
            if start < parse(other["end"]) and parse(other["start"]) < end:
                raise HTTPException(409, "time slot taken")
    i = _ids["booking"]
    _ids["booking"] += 1
    BOOKINGS[i] = {"id": i, "room_id": b.room_id, "start": b.start, "end": b.end, "attendees": b.attendees, "status": "confirmed"}
    return BOOKINGS[i]


@app.delete("/bookings/{bid}")
def cancel(bid: int):
    booking = BOOKINGS.get(bid)
    if booking is None or booking["status"] == "cancelled":
        raise HTTPException(404, "no such active booking")
    booking["status"] = "cancelled"
    return booking


@app.get("/rooms/{rid}/bookings")
def room_bookings(rid: int):
    if rid not in ROOMS:
        raise HTTPException(404, "no such room")
    rows = [b for b in BOOKINGS.values() if b["room_id"] == rid and b["status"] == "confirmed"]
    return sorted(rows, key=lambda b: parse(b["start"]))
