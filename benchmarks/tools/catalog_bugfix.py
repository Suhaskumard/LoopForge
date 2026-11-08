"""Bug-fixing tasks: a small broken project is embedded in the requirement; the model must return
the corrected project. `seed` is the broken code (shown), `reference` the fixed one (hidden).

The hidden tests check the reported symptom AND the behaviour that must keep working, so a rewrite
that breaks something else still fails.
"""

from typing import Any

INTRO = (
    "The FastAPI project below (entry point `app.main:app`) has a bug. Fix it so the behaviour described in "
    "SPEC holds, keep every existing endpoint/function and its signature, and return the COMPLETE corrected "
    "project including its unit tests (add a test that would have caught the bug)."
)


def _task(id_: str, difficulty: str, symptom: str, spec: str, seed: dict[str, str], ref: dict[str, str], test: str, criteria: list[str]) -> dict[str, Any]:
    files = "\n".join(f"File `{p}`:\n```python\n{c}```\n" for p, c in seed.items() if c.strip())
    req = f"{INTRO}\n\nSYMPTOM: {symptom}\n\nSPEC: {spec}\n\nExisting project files:\n\n{files}"
    return {
        "id": id_,
        "category": "bug_fixing",
        "difficulty": difficulty,
        "requirement": req,
        "acceptance_criteria": criteria,
        "reference": ref,
        "hidden_test": test,
        "seed": seed,
    }


INIT = {"app/__init__.py": ""}


def tasks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # 1 ---- pagination off by one ---------------------------------------------------------
    main = '''from fastapi import FastAPI, Query

app = FastAPI()
ITEMS = [f"item-{i}" for i in range(1, 24)]


def paginate(items, page, size):
    start = @@START@@
    return items[start : start + size]


@app.get("/items")
def list_items(page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=50)):
    data = paginate(ITEMS, page, size)
    return {"page": page, "size": size, "total": len(ITEMS), "items": data}
'''
    out.append(
        _task(
            "bug-01-pagination",
            "easy",
            "`GET /items?page=1&size=10` returns items 11-20 instead of the first ten, and page 3 of 23 items is empty.",
            "Pages are 1-based: page=1 returns items 1..size, page=2 the next `size` items, and so on. A page past the end returns an empty list. `total` is always the full item count.",
            {**INIT, "app/main.py": main.replace("@@START@@", "page * size")},
            {**INIT, "app/main.py": main.replace("@@START@@", "(page - 1) * size")},
            '''from fastapi.testclient import TestClient

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
''',
            ["Page 1 returns the first page", "Pages are 1-based", "Out-of-range pages return an empty list"],
        )
    )

    # 2 ---- statistics: integer division + empty list --------------------------------------
    stats_bad = '''def average(values):
    return sum(values) // len(values)


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
'''
    stats_ok = '''def average(values):
    if not values:
        return None
    return sum(values) / len(values)


def median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
'''
    main = '''from fastapi import FastAPI
from pydantic import BaseModel

from app.stats import average, median

app = FastAPI()


class Numbers(BaseModel):
    values: list[float]


@app.post("/stats")
def stats(n: Numbers):
    return {"count": len(n.values), "average": average(n.values), "median": median(n.values)}
'''
    out.append(
        _task(
            "bug-02-statistics",
            "medium",
            "`POST /stats` with values [1, 2] returns average 1 (not 1.5), the median of an even-length list is wrong, and an empty list crashes with a 500 error.",
            "`average` is the true arithmetic mean (float division); `median` of an even-length list is the mean of the two middle values; for an empty list both return None (and the endpoint answers 200 with null values and count 0).",
            {**INIT, "app/main.py": main, "app/stats.py": stats_bad},
            {**INIT, "app/main.py": main, "app/stats.py": stats_ok},
            '''import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stats import average, median

c = TestClient(app)


def post(values):
    r = c.post("/stats", json={"values": values})
    assert r.status_code == 200, r.text
    return r.json()


def test_mean_is_not_truncated():
    assert post([1, 2])["average"] == 1.5
    assert average([1, 2, 2]) == pytest.approx(5 / 3)


def test_median_odd_and_even():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5
    assert post([10, 20])["median"] == 15


def test_empty_list_is_handled():
    body = post([])
    assert body == {"count": 0, "average": None, "median": None}
    assert average([]) is None and median([]) is None


def test_single_value_and_negative():
    assert post([7])["average"] == 7 and post([7])["median"] == 7
    assert post([-1, -3])["average"] == -2


def test_input_is_not_mutated_and_floats_work():
    data = [3.5, 1.5, 2.5]
    median(data)
    assert data == [3.5, 1.5, 2.5]
    assert post(data)["average"] == pytest.approx(2.5)
''',
            ["Average uses true division", "Median handles even lengths", "Empty input yields null, not an error"],
        )
    )

    # 3 ---- api key prefix check ----------------------------------------------------------
    main = '''from fastapi import Depends, FastAPI, Header, HTTPException

app = FastAPI()
API_KEY = "sk-bench-12345"


def require_key(x_api_key: str | None = Header(default=None)):
    if x_api_key is None or not {check}:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/secret", dependencies=[Depends(require_key)])
def secret():
    return {{"data": "classified"}}


@app.get("/public")
def public():
    return {{"data": "hello"}}
'''
    out.append(
        _task(
            "bug-03-api-key",
            "easy",
            "Requests with the key `sk-bench-12345-extra` or `sk-bench-1` are accepted by `/secret` although only the exact key is valid.",
            "`/secret` requires the header `X-API-Key` to be EXACTLY the configured `API_KEY`. Compare in constant time (`hmac.compare_digest` or `secrets.compare_digest`). Missing or different keys -> 401. `/public` stays open.",
            {**INIT, "app/main.py": main.format(check="x_api_key.startswith(API_KEY[:10])")},
            {**INIT, "app/main.py": main.format(check="secrets.compare_digest(x_api_key, API_KEY)").replace("from fastapi import", "import secrets\n\nfrom fastapi import", 1)},
            '''import pytest
from fastapi.testclient import TestClient

from app.main import API_KEY, app

c = TestClient(app)


def test_exact_key_is_accepted():
    r = c.get("/secret", headers={"X-API-Key": API_KEY})
    assert r.status_code == 200 and r.json() == {"data": "classified"}


@pytest.mark.parametrize("key", [API_KEY + "-extra", API_KEY[:-1], API_KEY[:10], API_KEY.upper(), " " + API_KEY, "", "wrong"])
def test_anything_else_is_rejected(key):
    assert c.get("/secret", headers={"X-API-Key": key}).status_code == 401


def test_missing_header_is_401():
    assert c.get("/secret").status_code == 401


def test_public_endpoint_is_open():
    assert c.get("/public").json() == {"data": "hello"}


def test_comparison_is_constant_time():
    import inspect

    import app.main as m

    src = inspect.getsource(m)
    assert "compare_digest" in src
''',
            ["Only the exact API key is accepted", "Comparison is constant-time", "Public endpoint stays open"],
        )
    )

    # 4 ---- discount arithmetic -----------------------------------------------------------
    pricing_bad = '''def apply_discount(price, percent):
    return price - percent


def total(items):
    return sum(i["price"] * i["qty"] for i in items)
'''
    pricing_ok = '''from decimal import ROUND_HALF_UP, Decimal


def _d(x):
    return Decimal(str(x))


def apply_discount(price, percent):
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    result = _d(price) * (Decimal(100) - _d(percent)) / Decimal(100)
    return float(result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def total(items):
    return float(sum((_d(i["price"]) * i["qty"] for i in items), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
'''
    main = '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pricing import apply_discount, total

app = FastAPI()


class Item(BaseModel):
    price: float
    qty: int


class Cart(BaseModel):
    items: list[Item]
    discount_percent: float = 0


@app.post("/checkout")
def checkout(cart: Cart):
    raw = total([i.model_dump() for i in cart.items])
    try:
        final = apply_discount(raw, cart.discount_percent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"subtotal": raw, "total": final}
'''
    out.append(
        _task(
            "bug-04-discount",
            "medium",
            "A 10% discount on a 200.00 cart returns 190.00 (it subtracts 10) and totals show floating-point noise such as 0.30000000000000004.",
            "`apply_discount(price, percent)` takes a PERCENT (0-100) off the price and rounds half-up to 2 decimals (e.g. 19.99 with 15% -> 16.99); percent outside 0..100 raises ValueError (the endpoint then answers 422). `total` sums price*qty exactly and rounds half-up to 2 decimals.",
            {**INIT, "app/main.py": main, "app/pricing.py": pricing_bad},
            {**INIT, "app/main.py": main, "app/pricing.py": pricing_ok},
            '''import pytest
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
''',
            ["Discount is a percentage", "Money values are rounded half-up to two decimals", "Invalid percentages are rejected"],
        )
    )

    # 5 ---- case-sensitive duplicate users ------------------------------------------------
    main = '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
USERS: dict[str, dict] = {}


class NewUser(BaseModel):
    email: str
    name: str


@app.post("/users", status_code=201)
def create(u: NewUser):
    if u.email in USERS:
        raise HTTPException(status_code=409, detail="exists")
    USERS[u.email] = {"email": u.email, "name": u.name}
    return USERS[u.email]


@app.get("/users/{email}")
def get(email: str):
    if email not in USERS:
        raise HTTPException(status_code=404, detail="not found")
    return USERS[email]
'''
    fixed = main.replace("    if u.email in USERS:", "    email = u.email.strip().lower()\n    if email in USERS:").replace(
        '    USERS[u.email] = {"email": u.email, "name": u.name}\n    return USERS[u.email]',
        '    USERS[email] = {"email": email, "name": u.name}\n    return USERS[email]',
    ).replace("    if email not in USERS:\n        raise HTTPException(status_code=404", "    email = email.strip().lower()\n    if email not in USERS:\n        raise HTTPException(status_code=404").replace("    return USERS[email]\n", "    return USERS[email]\n")
    out.append(
        _task(
            "bug-05-case-insensitive-email",
            "easy",
            "`Ann@Example.com` and `ann@example.com` can both be registered, so one person gets two accounts; lookups are also case-sensitive.",
            "Emails are case-insensitive and whitespace around them is ignored: they are stored and returned lower-cased and stripped, a duplicate (ignoring case/whitespace) returns 409, and `GET /users/{email}` finds the user regardless of case.",
            {**INIT, "app/main.py": main},
            {**INIT, "app/main.py": fixed},
            '''import pytest
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
''',
            ["Emails are normalised to lower case", "Duplicate detection ignores case and whitespace", "Lookup is case-insensitive"],
        )
    )

    # 6 ---- delete works on a copy --------------------------------------------------------
    main = '''from fastapi import FastAPI, HTTPException, Response

app = FastAPI()
NOTES: dict[int, dict] = {{1: {{"id": 1, "text": "first"}}, 2: {{"id": 2, "text": "second"}}}}


@app.get("/notes")
def list_notes():
    return list(NOTES.values())


@app.delete("/notes/{{note_id}}", status_code=204)
def delete_note(note_id: int):
{body}


@app.post("/notes", status_code=201)
def add_note(note: dict):
    note_id = max(NOTES, default=0) + 1
    NOTES[note_id] = {{"id": note_id, "text": str(note.get("text", ""))}}
    return NOTES[note_id]
'''
    bad = '''    notes = dict(NOTES)
    if note_id not in notes:
        raise HTTPException(status_code=404, detail="not found")
    notes.pop(note_id)
    return Response(status_code=204)'''
    good = '''    if note_id not in NOTES:
        raise HTTPException(status_code=404, detail="not found")
    NOTES.pop(note_id)
    return Response(status_code=204)'''
    out.append(
        _task(
            "bug-06-delete-noop",
            "easy",
            "`DELETE /notes/1` returns 204 but the note is still listed afterwards.",
            "Deleting a note removes it for good: afterwards it is gone from `GET /notes`, a second delete returns 404, and ids of remaining notes are unchanged. New notes get `max(id)+1` (so ids are not reused while a higher id exists).",
            {**INIT, "app/main.py": main.format(body=bad)},
            {**INIT, "app/main.py": main.format(body=good)},
            '''import pytest
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
''',
            ["Deleted notes disappear from the list", "Deleting twice returns 404", "Id assignment is unchanged"],
        )
    )
    return out
