"""Detect breaking changes between two OpenAPI documents (Phase 18, docs/api_policy.md).

A change is **breaking** for existing clients if it:
* removes a path or an HTTP method,
* removes a response status code the old API documented as successful (2xx),
* adds a *required* request parameter or required request-body property,
* makes an optional request property required, or removes a request property that was accepted,
* removes a value from an enum used in a request (narrowing), or changes a property's type.
Adding paths, methods, optional inputs, response fields and enum values is **not** breaking.
Deliberate: the checker looks only at what a client must send and what success looked like - it does
not try to prove response-body compatibility beyond removed success codes, and it follows local
``$ref``s only. It is a tripwire for obvious breakage, not a proof of compatibility.
"""

from typing import Any

METHODS = ("get", "put", "post", "delete", "patch", "head", "options")


def _resolve(spec: dict[str, Any], node: Any, depth: int = 0) -> Any:
    while isinstance(node, dict) and "$ref" in node and depth < 20:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        cur: Any = spec
        for part in ref[2:].split("/"):
            cur = cur.get(part, {}) if isinstance(cur, dict) else {}
        node, depth = cur, depth + 1
    return node


def _body_schema(spec: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    body = _resolve(spec, op.get("requestBody", {}))
    for media in (body.get("content") or {}).values():
        return _resolve(spec, media.get("schema", {})) or {}
    return {}


def _types(schema: dict[str, Any]) -> set[str]:
    kinds = {schema["type"]} if isinstance(schema.get("type"), str) else set()
    for key in ("anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            if isinstance(sub, dict) and isinstance(sub.get("type"), str):
                kinds.add(sub["type"])
    return kinds - {"null"}


def _compare_schema(
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
    old: dict[str, Any],
    new: dict[str, Any],
    where: str,
    out: list[str],
    depth: int = 0,
) -> None:
    old, new = _resolve(old_spec, old), _resolve(new_spec, new)
    if depth > 6 or not isinstance(old, dict) or not isinstance(new, dict):
        return
    if old.get("enum") and new.get("enum"):
        gone = set(map(str, old["enum"])) - set(map(str, new["enum"]))
        if gone:
            out.append(f"{where}: enum value(s) no longer accepted: {sorted(gone)}")
    ot, nt = _types(old), _types(new)
    if ot and nt and not ot <= nt:
        out.append(f"{where}: type changed from {sorted(ot)} to {sorted(nt)}")
    old_props, new_props = old.get("properties") or {}, new.get("properties") or {}
    old_req, new_req = set(old.get("required") or []), set(new.get("required") or [])
    for name in old_props:
        if new_props and name not in new_props:
            out.append(f"{where}: property '{name}' removed")
    for name in new_props:
        if name in new_req and name not in old_req:
            out.append(f"{where}: property '{name}' is newly required")
    for name in set(old_props) & set(new_props):
        _compare_schema(
            old_spec, new_spec, old_props[name], new_props[name], f"{where}.{name}", out, depth + 1
        )


def breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for path, old_item in (old.get("paths") or {}).items():
        new_item = (new.get("paths") or {}).get(path)
        if new_item is None:
            out.append(f"{path}: path removed")
            continue
        for method in METHODS:
            if method not in old_item:
                continue
            tag = f"{method.upper()} {path}"
            if method not in new_item:
                out.append(f"{tag}: method removed")
                continue
            o, n = old_item[method], new_item[method]
            old_ok = {c for c in (o.get("responses") or {}) if str(c).startswith("2")}
            new_ok = {c for c in (n.get("responses") or {}) if str(c).startswith("2")}
            if old_ok and not old_ok & new_ok:
                out.append(f"{tag}: success status {sorted(old_ok)} replaced by {sorted(new_ok)}")
            old_params = {
                (p["in"], p["name"]): p
                for p in map(lambda x: _resolve(old, x), o.get("parameters", []))
            }
            for p in map(lambda x: _resolve(new, x), n.get("parameters", [])):
                key = (p["in"], p["name"])
                if p.get("required") and (
                    key not in old_params or not old_params[key].get("required")
                ):
                    out.append(f"{tag}: parameter '{p['name']}' ({p['in']}) is newly required")
            for key in old_params:
                if key not in {
                    (p["in"], p["name"])
                    for p in map(lambda x: _resolve(new, x), n.get("parameters", []))
                }:
                    out.append(f"{tag}: parameter '{key[1]}' ({key[0]}) removed")
            if n.get("requestBody", {}).get("required") and not o.get("requestBody", {}).get(
                "required"
            ):
                out.append(f"{tag}: request body is newly required")
            _compare_schema(
                old, new, _body_schema(old, o), _body_schema(new, n), f"{tag} body", out
            )
    return out
