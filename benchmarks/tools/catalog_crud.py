"""CRUD tasks: six resources with different fields, constraints and uniqueness rules.

Reference solution and hidden test are both generated from the same field spec, so the contract
text given to the model is exactly what the hidden tests check. The tasks differ in the rules a
model has to get right (ranges, patterns, enums, defaults, unique keys, dates).
"""

from typing import Any

# field spec: name, python type, pydantic constraint, valid sample, [invalid samples], note
RESOURCES: list[dict[str, Any]] = [
    {
        "id": "crud-01-employees",
        "noun": "employee",
        "plural": "employees",
        "difficulty": "easy",
        "fields": [
            ("name", "str", "Field(min_length=1, max_length=100)", "Ada Lovelace", ["", "x" * 101], "1-100 chars"),
            ("email", "str", "Field(pattern=r'^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$')", "ada@example.com", ["not-an-email"], "valid email shape"),
            ("salary", "float", "Field(ge=0)", 5000.5, [-1], "not negative"),
            ("department", "str", "Field(min_length=1)", "Engineering", [""], "non-empty"),
        ],
        "unique": "email",
    },
    {
        "id": "crud-02-books",
        "noun": "book",
        "plural": "books",
        "difficulty": "easy",
        "fields": [
            ("title", "str", "Field(min_length=1, max_length=200)", "Dune", ["", "t" * 201], "1-200 chars"),
            ("isbn", "str", "Field(pattern=r'^\\d{13}$')", "9780441172719", ["123", "abcdefghijklm"], "exactly 13 digits"),
            ("price", "float", "Field(gt=0)", 9.99, [0, -5], "greater than 0"),
            ("stock", "int", "Field(ge=0)", 4, [-1], "0 or more"),
        ],
        "unique": "isbn",
    },
    {
        "id": "crud-03-products",
        "noun": "product",
        "plural": "products",
        "difficulty": "medium",
        "fields": [
            ("sku", "str", "Field(pattern=r'^[A-Z]{3}-\\d{3}$')", "ABC-123", ["abc-123", "ABCD-12", "ABC123"], "three capitals, dash, three digits"),
            ("name", "str", "Field(min_length=2)", "Widget", ["a"], "at least 2 chars"),
            ("price", "float", "Field(gt=0, le=100000)", 19.5, [0, 100001], "greater than 0 and at most 100000"),
        ],
        "unique": "sku",
    },
    {
        "id": "crud-04-tickets",
        "noun": "ticket",
        "plural": "tickets",
        "difficulty": "medium",
        "fields": [
            ("title", "str", "Field(min_length=3)", "Printer broken", ["ab"], "at least 3 chars"),
            ("priority", "int", "Field(ge=1, le=5)", 3, [0, 6], "1 to 5"),
            ("status", "Literal['open', 'in_progress', 'closed']", "'open'", "in_progress", ["done"], "one of open, in_progress, closed; defaults to open when omitted"),
        ],
        "unique": None,
        "optional": {"status": "open"},
    },
    {
        "id": "crud-05-students",
        "noun": "student",
        "plural": "students",
        "difficulty": "easy",
        "fields": [
            ("name", "str", "Field(min_length=1)", "Grace Hopper", [""], "non-empty"),
            ("grade", "int", "Field(ge=0, le=100)", 88, [-1, 101], "0 to 100"),
            ("email", "str", "Field(pattern=r'^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$')", "grace@example.com", ["nope"], "valid email shape"),
        ],
        "unique": "email",
    },
    {
        "id": "crud-06-events",
        "noun": "event",
        "plural": "events",
        "difficulty": "hard",
        "fields": [
            ("title", "str", "Field(min_length=1)", "Launch", [""], "non-empty"),
            ("capacity", "int", "Field(ge=1, le=1000)", 50, [0, 1001], "1 to 1000"),
            ("starts_on", "date", "Field()", "2030-05-01", ["2030-13-45", "tomorrow"], "an ISO date (YYYY-MM-DD)"),
        ],
        "unique": None,
        "extra": "Listing supports `?min_capacity=N` returning only events with capacity >= N.",
    },
]


def _model_lines(spec: dict[str, Any]) -> str:
    out = []
    for name, typ, constraint, *_ in spec["fields"]:
        if name in spec.get("optional", {}):
            out.append(f"    {name}: {typ} = {constraint}")
        else:
            out.append(f"    {name}: {typ} = {constraint}")
    return "\n".join(out)


def _reference(spec: dict[str, Any]) -> dict[str, str]:
    plural, noun = spec["plural"], spec["noun"]
    uniq = spec["unique"]
    imports = "from datetime import date\n" if any(f[1] == "date" for f in spec["fields"]) else ""
    literal = "from typing import Literal\n" if any("Literal" in f[1] for f in spec["fields"]) else ""
    dup = (
        f"    if any(r['{uniq}'] == data['{uniq}'] for r in DB.values()):\n"
        f"        raise HTTPException(status_code=409, detail='duplicate {uniq}')\n"
        if uniq
        else ""
    )
    dup_update = (
        f"    if any(r['{uniq}'] == data['{uniq}'] and i != item_id for i, r in DB.items()):\n"
        f"        raise HTTPException(status_code=409, detail='duplicate {uniq}')\n"
        if uniq
        else ""
    )
    list_filter = (
        "    if min_capacity is not None:\n"
        "        rows = [r for r in rows if r['capacity'] >= min_capacity]\n"
        if spec.get("extra")
        else ""
    )
    list_arg = ", min_capacity: int | None = None" if spec.get("extra") else ""
    # fields with a literal default are optional on input
    fields = []
    for name, typ, constraint, *_ in spec["fields"]:
        fields.append(f"    {name}: {typ} = {constraint}")
    main = f'''{imports}{literal}from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

app = FastAPI()
DB: dict[int, dict] = {{}}
_next = {{"id": 1}}


class Item(BaseModel):
{chr(10).join(fields)}


def _dump(item: Item) -> dict:
    return item.model_dump(mode="json")


def reset() -> None:
    DB.clear()
    _next["id"] = 1


@app.post("/{plural}", status_code=201)
def create(item: Item):
    data = _dump(item)
{dup}    item_id = _next["id"]
    _next["id"] += 1
    DB[item_id] = {{**data, "id": item_id}}
    return DB[item_id]


@app.get("/{plural}")
def list_items(skip: int = 0, limit: int = 100{list_arg}):
    rows = list(DB.values())
{list_filter}    return rows[skip : skip + limit]


@app.get("/{plural}/{{item_id}}")
def get_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="{noun} not found")
    return DB[item_id]


@app.put("/{plural}/{{item_id}}")
def update(item_id: int, item: Item):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="{noun} not found")
    data = _dump(item)
{dup_update}    DB[item_id] = {{**data, "id": item_id}}
    return DB[item_id]


@app.delete("/{plural}/{{item_id}}", status_code=204)
def delete(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="{noun} not found")
    del DB[item_id]
    return Response(status_code=204)
'''
    return {"app/__init__.py": "", "app/main.py": main}


def _requirement(spec: dict[str, Any]) -> str:
    plural, noun = spec["plural"], spec["noun"]
    lines = [
        f"Build a FastAPI application whose entry point is `app.main:app` (variable `app` in `app/main.py`)"
        f" that manages {plural} in memory (no database).",
        "",
        f"A {noun} has these fields (all required unless stated otherwise); invalid input must return HTTP 422:",
    ]
    for name, typ, _c, _v, _bad, note in spec["fields"]:
        lines.append(f"- `{name}` ({typ.split('[')[0].lower()}): {note}")
    lines += [
        "",
        "Endpoints:",
        f"- `POST /{plural}` -> 201 with the created {noun} as JSON, including an integer `id` assigned by the server (1, 2, 3, ...).",
        f"- `GET /{plural}` -> 200 list of {plural} (supports `skip` and `limit` query parameters, default skip=0, limit=100).",
        f"- `GET /{plural}/{{id}}` -> 200 or 404 if it does not exist.",
        f"- `PUT /{plural}/{{id}}` -> replaces all fields, 200 with the updated {noun}, 404 if missing, 422 if invalid.",
        f"- `DELETE /{plural}/{{id}}` -> 204, 404 if missing; afterwards GET returns 404.",
    ]
    if spec["unique"]:
        lines.append(
            f"- `{spec['unique']}` must be unique: creating a duplicate returns 409 (updating a {noun} to another's `{spec['unique']}` also returns 409; keeping its own is fine)."
        )
    if spec.get("extra"):
        lines.append(f"- {spec['extra']}")
    lines += [
        "",
        "Also define a function `reset()` in `app/main.py` that deletes all stored data and restarts the id counter at 1 (used by the test harness).",
        "Include unit tests (pytest) for the endpoints.",
    ]
    return "\n".join(lines)


def _criteria(spec: dict[str, Any]) -> list[str]:
    plural = spec["plural"]
    crit = [
        f"All five {plural} endpoints exist with the specified status codes",
        "Invalid input returns 422 and unknown ids return 404",
        "Unit tests cover create, read, update and delete",
    ]
    if spec["unique"]:
        crit.append(f"Duplicate {spec['unique']} returns 409")
    return crit


def _hidden_test(spec: dict[str, Any]) -> str:
    plural = spec["plural"]
    uniq = spec["unique"]
    valid = {f[0]: f[3] for f in spec["fields"]}
    optional = spec.get("optional", {})
    bad_cases: list[tuple[str, Any]] = []
    for name, _t, _c, _v, bads, _n in spec["fields"]:
        for b in bads:
            bad_cases.append((name, b))
    other = dict(valid)
    for name, typ, *_ in spec["fields"]:
        if name == uniq:
            other[name] = _other_unique(valid[name])
    t = f'''import pytest
from fastapi.testclient import TestClient

from app.main import app

VALID = {valid!r}
OTHER = {other!r}
BAD = {bad_cases!r}
URL = "/{plural}"


@pytest.fixture()
def client():
    import app.main as m

    m.reset()
    return TestClient(app)


def test_create_and_get(client):
    r = client.post(URL, json=VALID)
    assert r.status_code == 201, r.text
    body = r.json()
    assert isinstance(body["id"], int)
    for k, v in VALID.items():
        assert body[k] == v
    g = client.get(f"{{URL}}/{{body['id']}}")
    assert g.status_code == 200 and g.json() == body


def test_ids_are_assigned_in_sequence_per_new_item(client):
    a = client.post(URL, json=VALID).json()["id"]
    b = client.post(URL, json=OTHER).json()["id"]
    assert (a, b) == (1, 2)


@pytest.mark.parametrize("field,value", BAD)
def test_invalid_field_is_rejected(client, field, value):
    payload = {{**VALID, field: value}}
    assert client.post(URL, json=payload).status_code == 422


def test_missing_required_field_is_rejected(client):
    required = [k for k in VALID if k not in {sorted(optional)!r}]
    for k in required:
        payload = {{x: y for x, y in VALID.items() if x != k}}
        assert client.post(URL, json=payload).status_code == 422, k


def test_unknown_id_is_404(client):
    assert client.get(f"{{URL}}/999").status_code == 404
    assert client.put(f"{{URL}}/999", json=VALID).status_code == 404
    assert client.delete(f"{{URL}}/999").status_code == 404


def test_list_and_paging(client):
    assert client.get(URL).json() == []
    ids = [client.post(URL, json=VALID if i == 0 else OTHER_N(i)).json()["id"] for i in range(3)]
    assert [r["id"] for r in client.get(URL).json()] == ids
    assert [r["id"] for r in client.get(URL, params={{"skip": 1, "limit": 1}}).json()] == [ids[1]]


def OTHER_N(i):
    data = dict(OTHER)
    key = {uniq!r}
    if key:
        data[key] = _vary(data[key], i)
    return data


def _vary(value, i):
    if isinstance(value, str) and "@" in value:
        name, dom = value.split("@")
        return f"{{name}}{{i}}@{{dom}}"
    if isinstance(value, str) and value.isdigit():
        return value[:-1] + str((int(value[-1]) + i) % 10)
    if isinstance(value, str) and "-" in value:
        head, tail = value.rsplit("-", 1)
        return f"{{head}}-{{int(tail) + i:03d}}"
    return value


def test_update_replaces_all_fields(client):
    item = client.post(URL, json=VALID).json()
    r = client.put(f"{{URL}}/{{item['id']}}", json=OTHER)
    assert r.status_code == 200, r.text
    for k, v in OTHER.items():
        assert r.json()[k] == v
    assert r.json()["id"] == item["id"]
    assert client.get(f"{{URL}}/{{item['id']}}").json()["id"] == item["id"]


def test_update_validates(client):
    item = client.post(URL, json=VALID).json()
    if BAD:
        field, value = BAD[0]
        assert client.put(f"{{URL}}/{{item['id']}}", json={{**VALID, field: value}}).status_code == 422


def test_delete_then_gone(client):
    item = client.post(URL, json=VALID).json()
    assert client.delete(f"{{URL}}/{{item['id']}}").status_code == 204
    assert client.get(f"{{URL}}/{{item['id']}}").status_code == 404
    assert client.get(URL).json() == []
'''
    if uniq:
        t += f'''

def test_duplicate_unique_key_is_409(client):
    client.post(URL, json=VALID)
    assert client.post(URL, json={{**OTHER, "{uniq}": VALID["{uniq}"]}}).status_code == 409


def test_update_to_anothers_unique_key_is_409_but_own_key_is_fine(client):
    a = client.post(URL, json=VALID).json()
    b = client.post(URL, json=OTHER).json()
    assert client.put(f"{{URL}}/{{b['id']}}", json={{**OTHER, "{uniq}": VALID["{uniq}"]}}).status_code == 409
    assert client.put(f"{{URL}}/{{a['id']}}", json=VALID).status_code == 200
'''
    if "status" in optional:
        t += '''

def test_status_defaults_to_open(client):
    payload = {k: v for k, v in VALID.items() if k != "status"}
    r = client.post(URL, json=payload)
    assert r.status_code == 201 and r.json()["status"] == "open"
'''
    if spec.get("extra"):
        t += '''

def test_min_capacity_filter(client):
    client.post(URL, json={**VALID, "capacity": 10})
    client.post(URL, json={**OTHER, "capacity": 100})
    rows = client.get(URL, params={"min_capacity": 50}).json()
    assert [r["capacity"] for r in rows] == [100]
    assert len(client.get(URL, params={"min_capacity": 1}).json()) == 2
'''
    return t


def _other_unique(value: Any) -> Any:
    if isinstance(value, str) and "@" in value:
        name, dom = value.split("@")
        return f"other.{name}@{dom}"
    if isinstance(value, str) and value.isdigit():
        return value[:-1] + str((int(value[-1]) + 1) % 10)
    if isinstance(value, str) and "-" in value:
        head, tail = value.rsplit("-", 1)
        return f"{head}-{int(tail) + 1:03d}"
    return value


def tasks() -> list[dict[str, Any]]:
    out = []
    for spec in RESOURCES:
        out.append(
            {
                "id": spec["id"],
                "category": "crud",
                "difficulty": spec["difficulty"],
                "requirement": _requirement(spec),
                "acceptance_criteria": _criteria(spec),
                "reference": _reference(spec),
                "hidden_test": _hidden_test(spec),
                "seed": None,
            }
        )
    return out
