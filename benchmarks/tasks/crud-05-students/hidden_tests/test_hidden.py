import pytest
from fastapi.testclient import TestClient

from app.main import app

VALID = {'name': 'Grace Hopper', 'grade': 88, 'email': 'grace@example.com'}
OTHER = {'name': 'Grace Hopper', 'grade': 88, 'email': 'other.grace@example.com'}
BAD = [('name', ''), ('grade', -1), ('grade', 101), ('email', 'nope')]
URL = "/students"


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
    g = client.get(f"{URL}/{body['id']}")
    assert g.status_code == 200 and g.json() == body


def test_ids_are_assigned_in_sequence_per_new_item(client):
    a = client.post(URL, json=VALID).json()["id"]
    b = client.post(URL, json=OTHER).json()["id"]
    assert (a, b) == (1, 2)


@pytest.mark.parametrize("field,value", BAD)
def test_invalid_field_is_rejected(client, field, value):
    payload = {**VALID, field: value}
    assert client.post(URL, json=payload).status_code == 422


def test_missing_required_field_is_rejected(client):
    required = [k for k in VALID if k not in []]
    for k in required:
        payload = {x: y for x, y in VALID.items() if x != k}
        assert client.post(URL, json=payload).status_code == 422, k


def test_unknown_id_is_404(client):
    assert client.get(f"{URL}/999").status_code == 404
    assert client.put(f"{URL}/999", json=VALID).status_code == 404
    assert client.delete(f"{URL}/999").status_code == 404


def test_list_and_paging(client):
    assert client.get(URL).json() == []
    ids = [client.post(URL, json=VALID if i == 0 else OTHER_N(i)).json()["id"] for i in range(3)]
    assert [r["id"] for r in client.get(URL).json()] == ids
    assert [r["id"] for r in client.get(URL, params={"skip": 1, "limit": 1}).json()] == [ids[1]]


def OTHER_N(i):
    data = dict(OTHER)
    key = 'email'
    if key:
        data[key] = _vary(data[key], i)
    return data


def _vary(value, i):
    if isinstance(value, str) and "@" in value:
        name, dom = value.split("@")
        return f"{name}{i}@{dom}"
    if isinstance(value, str) and value.isdigit():
        return value[:-1] + str((int(value[-1]) + i) % 10)
    if isinstance(value, str) and "-" in value:
        head, tail = value.rsplit("-", 1)
        return f"{head}-{int(tail) + i:03d}"
    return value


def test_update_replaces_all_fields(client):
    item = client.post(URL, json=VALID).json()
    r = client.put(f"{URL}/{item['id']}", json=OTHER)
    assert r.status_code == 200, r.text
    for k, v in OTHER.items():
        assert r.json()[k] == v
    assert r.json()["id"] == item["id"]
    assert client.get(f"{URL}/{item['id']}").json()["id"] == item["id"]


def test_update_validates(client):
    item = client.post(URL, json=VALID).json()
    if BAD:
        field, value = BAD[0]
        assert client.put(f"{URL}/{item['id']}", json={**VALID, field: value}).status_code == 422


def test_delete_then_gone(client):
    item = client.post(URL, json=VALID).json()
    assert client.delete(f"{URL}/{item['id']}").status_code == 204
    assert client.get(f"{URL}/{item['id']}").status_code == 404
    assert client.get(URL).json() == []


def test_duplicate_unique_key_is_409(client):
    client.post(URL, json=VALID)
    assert client.post(URL, json={**OTHER, "email": VALID["email"]}).status_code == 409


def test_update_to_anothers_unique_key_is_409_but_own_key_is_fine(client):
    a = client.post(URL, json=VALID).json()
    b = client.post(URL, json=OTHER).json()
    assert client.put(f"{URL}/{b['id']}", json={**OTHER, "email": VALID["email"]}).status_code == 409
    assert client.put(f"{URL}/{a['id']}", json=VALID).status_code == 200
