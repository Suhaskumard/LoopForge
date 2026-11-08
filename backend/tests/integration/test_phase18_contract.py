"""Phase 18: the public API contract: version, OpenAPI snapshot, breaking changes, deprecation."""

import copy
import json
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deprecation import deprecated
from app.main import app
from app.utils.openapi_compat import breaking_changes
from app.version import __version__

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str) -> dict:
    return json.loads((ROOT / "docs" / name).read_text(encoding="utf-8"))


def test_one_version_everywhere(client):
    assert __version__ == "1.0.0-rc1"
    assert app.openapi()["info"]["version"] == __version__
    assert client.get("/health").json() == {"status": "ok", "version": __version__}
    assert _load("openapi.json")["info"]["version"] == __version__


def test_openapi_snapshot_is_current():
    live = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    snap = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")
    assert live == snap, "API changed: run `python scripts/export_openapi.py` and review the diff"


def test_the_api_has_not_broken_since_the_phase_17_baseline():
    """docs/openapi.baseline.json is the API as of Phase 17 (the last pre-release surface)."""
    assert breaking_changes(_load("openapi.baseline.json"), app.openapi()) == []


# ---- the detector itself -----------------------------------------------------------------------


def spec(**ops):
    return {"openapi": "3.1.0", "paths": ops, "components": {"schemas": {}}}


def op(params=None, body=None, responses=None, body_required=True):
    out: dict = {"responses": responses or {"200": {"description": "ok"}}}
    if params:
        out["parameters"] = params
    if body:
        out["requestBody"] = {
            "required": body_required,
            "content": {"application/json": {"schema": body}},
        }
    return out


def q(name, required=False):
    return {"name": name, "in": "query", "required": required, "schema": {"type": "string"}}


BODY = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "kind": {"enum": ["a", "b"], "type": "string"}},
    "required": ["name"],
}


def test_detector_accepts_additive_changes():
    old = spec(**{"/x": {"get": op([q("a")]), "post": op(body=BODY)}})
    new = copy.deepcopy(old)
    new["paths"]["/y"] = {"get": op()}  # new path
    new["paths"]["/x"]["put"] = op()  # new method
    new["paths"]["/x"]["get"]["parameters"].append(q("b"))  # new optional input
    new["paths"]["/x"]["post"]["requestBody"]["content"]["application/json"]["schema"] = {
        **BODY,
        "properties": {**BODY["properties"], "extra": {"type": "integer"}},
    }
    new["paths"]["/x"]["post"]["requestBody"]["content"]["application/json"]["schema"][
        "properties"
    ]["kind"]["enum"] = ["a", "b", "c"]  # widened enum
    assert breaking_changes(old, new) == []


def test_detector_flags_each_kind_of_breakage():
    old = spec(**{"/x": {"get": op([q("a")]), "post": op(body=BODY)}, "/gone": {"get": op()}})
    new = copy.deepcopy(old)
    del new["paths"]["/gone"]
    del new["paths"]["/x"]["get"]
    found = breaking_changes(old, new)
    assert any("/gone: path removed" in f for f in found)
    assert any("GET /x: method removed" in f for f in found)

    cases = {
        "newly required": lambda n: n["paths"]["/x"]["get"].update(
            parameters=[q("a"), q("z", True)]
        ),
        "removed": lambda n: n["paths"]["/x"]["get"].update(parameters=[]),
        "success status": lambda n: n["paths"]["/x"]["get"].update(responses={"204": {}}),
    }
    for needle, mutate in cases.items():
        new = copy.deepcopy(old)
        mutate(new)
        assert any(needle in f for f in breaking_changes(old, new)), needle

    body_cases = {
        "removed": {**BODY, "properties": {"name": {"type": "string"}}},
        "newly required": {**BODY, "required": ["name", "kind"]},
        "no longer accepted": {
            **BODY,
            "properties": {"name": {"type": "string"}, "kind": {"enum": ["a"], "type": "string"}},
        },
        "type changed": {
            **BODY,
            "properties": {"name": {"type": "integer"}, "kind": BODY["properties"]["kind"]},
        },
    }
    for needle, schema in body_cases.items():
        new = copy.deepcopy(old)
        new["paths"]["/x"]["post"]["requestBody"]["content"]["application/json"]["schema"] = schema
        assert any(needle in f for f in breaking_changes(old, new)), needle

    new = copy.deepcopy(old)
    new["paths"]["/x"]["post"]["requestBody"]["required"] = True
    old["paths"]["/x"]["post"]["requestBody"]["required"] = False
    assert any("body is newly required" in f for f in breaking_changes(old, new))


def test_detector_follows_local_refs():
    old = spec(**{"/x": {"post": op(body={"$ref": "#/components/schemas/B"})}})
    old["components"]["schemas"]["B"] = BODY
    new = copy.deepcopy(old)
    new["components"]["schemas"]["B"] = {**BODY, "required": ["name", "kind"]}
    assert any("newly required" in f for f in breaking_changes(old, new))


# ---- deprecation headers -----------------------------------------------------------------------


def test_deprecated_routes_carry_deprecation_sunset_and_successor_headers():
    mini = FastAPI()
    dep = deprecated(sunset="2027-03-01", successor="/api/v1/new")

    @mini.get("/old", deprecated=True, dependencies=[Depends(dep)])
    def old() -> dict:
        return {}

    @mini.get("/fine")
    def fine() -> dict:
        return {}

    c = TestClient(mini)
    r = c.get("/old")
    assert r.headers["deprecation"] == "true"
    assert r.headers["sunset"] == "Mon, 01 Mar 2027 00:00:00 GMT"
    assert r.headers["link"] == '</api/v1/new>; rel="successor-version"'
    assert "deprecation" not in c.get("/fine").headers
    assert mini.openapi()["paths"]["/old"]["get"]["deprecated"] is True
