# ruff: noqa: E501
"""Phase 17: SCIM 2.0 provisioning - conformance against our own client (not against Okta/Entra)."""

import uuid

import pytest

from app.database.models import AuditLog, Membership, ScimIdentity, User
from tests.conftest import register_and_login

API = "/api/v1"
S = f"{API}/scim/v2"
USER = "urn:ietf:params:scim:schemas:core:2.0:User"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERR = "urn:ietf:params:scim:api:messages:2.0:Error"


def patch(*ops):
    return {"schemas": [PATCH], "Operations": list(ops)}


@pytest.fixture
def org(client):
    h = register_and_login(client, "admin@corp.example")
    o = client.get(f"{API}/orgs", headers=h).json()[0]
    hh = {**h, "X-Org-Id": o["id"]}
    r = client.post(f"{API}/orgs/{o['id']}/scim-tokens", json={"name": "okta"}, headers=hh)
    assert r.status_code == 201, r.text
    return {
        "id": o["id"], "admin": hh, "token": r.json()["token"], "token_id": r.json()["id"],
        "scim": {"Authorization": f"Bearer {r.json()['token']}"},
    }  # fmt: skip


def mk(client, org, email="ann@corp.example", **extra):
    r = client.post(
        f"{S}/Users",
        json={"schemas": [USER], "userName": email, "externalId": "ext-1", **extra},
        headers=org["scim"],
    )
    return r


def test_token_is_shown_once_stored_hashed_and_listed_without_the_secret(client, org):
    listing = client.get(f"{API}/orgs/{org['id']}/scim-tokens", headers=org["admin"]).json()
    assert listing[0]["prefix"] == org["token"][:8] and "token" not in listing[0]
    assert org["token"].startswith("lfs_")


def test_service_provider_config_and_content_type(client, org):
    r = client.get(f"{S}/ServiceProviderConfig", headers=org["scim"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/scim+json")
    assert r.json()["patch"]["supported"] is True and r.json()["bulk"]["supported"] is False


def test_only_a_scim_token_works(client, org):
    admin_jwt = {"Authorization": org["admin"]["Authorization"]}
    for h in ({}, admin_jwt, {"Authorization": "Bearer lfs_wrong"}, {"Authorization": "Basic x"}):
        r = client.get(f"{S}/Users", headers=h)
        assert r.status_code == 401
        assert r.json()["schemas"] == [ERR] and r.json()["status"] == "401"
    # and a SCIM token is not an API/session credential
    assert client.get(f"{API}/projects", headers=org["scim"]).status_code == 401


def test_create_get_list_and_filter(client, org):
    r = mk(client, org)
    assert r.status_code == 201, r.text
    u = r.json()
    assert (
        u["userName"] == "ann@corp.example" and u["active"] is True and u["externalId"] == "ext-1"
    )
    assert client.get(f"{S}/Users/{u['id']}", headers=org["scim"]).json()["id"] == u["id"]
    mk(client, org, "bob@corp.example", externalId="ext-2")
    full = client.get(f"{S}/Users", headers=org["scim"]).json()
    assert full["totalResults"] == 2 and full["itemsPerPage"] == 2 and full["startIndex"] == 1
    one = client.get(
        f"{S}/Users", params={"filter": 'userName eq "BOB@corp.example"'}, headers=org["scim"]
    ).json()
    assert one["totalResults"] == 1 and one["Resources"][0]["userName"] == "bob@corp.example"
    ext = client.get(
        f"{S}/Users", params={"filter": 'externalId eq "ext-1"'}, headers=org["scim"]
    ).json()
    assert ext["Resources"][0]["userName"] == "ann@corp.example"
    none = client.get(f"{S}/Users", params={"filter": 'userName eq "x@y.z"'}, headers=org["scim"])
    assert none.json()["totalResults"] == 0 and none.json()["Resources"] == []


def test_pagination(client, org):
    for i in range(5):
        mk(client, org, f"u{i}@corp.example", externalId=f"e{i}")
    page = client.get(
        f"{S}/Users", params={"startIndex": 3, "count": 2}, headers=org["scim"]
    ).json()
    assert page["totalResults"] == 5 and page["itemsPerPage"] == 2 and page["startIndex"] == 3
    zero = client.get(f"{S}/Users", params={"count": 0}, headers=org["scim"]).json()
    assert zero["Resources"] == [] and zero["totalResults"] == 5


@pytest.mark.parametrize(
    "flt",
    [
        'userName co "a"',
        "userName eq x",
        'displayName eq "x"',
        'userName eq "a" and active eq true',
    ],
)
def test_unsupported_filters_are_rejected_with_invalid_filter(client, org, flt):
    r = client.get(f"{S}/Users", params={"filter": flt}, headers=org["scim"])
    assert r.status_code == 400 and r.json()["scimType"] == "invalidFilter"


def test_duplicate_and_invalid_create(client, org):
    assert mk(client, org).status_code == 201
    dup = mk(client, org)
    assert dup.status_code == 409 and dup.json()["scimType"] == "uniqueness"
    bad = client.post(f"{S}/Users", json={"userName": "not-an-email"}, headers=org["scim"])
    assert bad.status_code == 400 and bad.json()["scimType"] == "invalidValue"


def test_new_user_has_a_developer_membership_no_password_and_verified_email(client, org):
    u = mk(client, org).json()
    with client.factory() as db:
        user = db.get(User, uuid.UUID(u["id"]))
        assert user.password_hash is None and user.email_verified_at is not None
        m = db.query(Membership).filter_by(user_id=user.id).one()
        assert (m.role, m.source, str(m.org_id)) == ("developer", "scim", org["id"])


def test_role_via_roles_attribute_and_group_patch(client, org):
    u = mk(client, org, roles=[{"value": "viewer"}]).json()
    g = client.get(f"{S}/Groups", headers=org["scim"]).json()
    assert [x["id"] for x in g["Resources"]] == ["viewer", "developer", "approver", "admin"]
    viewers = next(x for x in g["Resources"] if x["id"] == "viewer")
    assert [m["value"] for m in viewers["members"]] == [u["id"]]
    r = client.patch(
        f"{S}/Groups/approver",
        json=patch({"op": "add", "path": "members", "value": [{"value": u["id"]}]}),
        headers=org["scim"],
    )
    assert r.status_code == 200 and [m["value"] for m in r.json()["members"]] == [u["id"]]
    with client.factory() as db:
        assert db.query(Membership).filter_by(user_id=uuid.UUID(u["id"])).one().role == "approver"
    r = client.patch(
        f"{S}/Groups/approver",
        json=patch({"op": "remove", "path": f'members[value eq "{u["id"]}"]'}),
        headers=org["scim"],
    )
    assert r.status_code == 200 and r.json()["members"] == []
    with client.factory() as db:
        assert db.query(Membership).filter_by(user_id=uuid.UUID(u["id"])).one().role == "viewer"


def test_group_errors(client, org):
    assert client.get(f"{S}/Groups/root", headers=org["scim"]).status_code == 404
    r = client.patch(
        f"{S}/Groups/viewer",
        json=patch({"op": "replace", "path": "displayName", "value": "x"}),
        headers=org["scim"],
    )
    assert r.status_code == 400 and r.json()["scimType"] == "invalidPath"
    r = client.patch(
        f"{S}/Groups/viewer",
        json=patch({"op": "add", "path": "members", "value": [{"value": str(uuid.uuid4())}]}),
        headers=org["scim"],
    )
    assert r.status_code == 404


def test_deactivate_via_patch_removes_access_in_this_org_but_keeps_the_record(client, org):
    u = mk(client, org).json()
    assert (
        client.patch(
            f"{S}/Users/{u['id']}",
            json=patch({"op": "replace", "path": "active", "value": False}),
            headers=org["scim"],
        ).json()["active"]
        is False
    )
    got = client.get(f"{S}/Users/{u['id']}", headers=org["scim"]).json()
    assert got["active"] is False
    with client.factory() as db:
        assert db.query(Membership).filter_by(user_id=uuid.UUID(u["id"])).count() == 0
        assert db.get(User, uuid.UUID(u["id"])).active is False  # sole org -> account disabled
        actions = {a.action for a in db.query(AuditLog).filter_by(org_id=uuid.UUID(org["id"]))}
    assert {"scim.user_created", "scim.user_deactivated", "scim.token_created"} <= actions
    back = client.patch(
        f"{S}/Users/{u['id']}",
        json=patch({"op": "replace", "value": {"active": "True"}}),  # Entra sends strings
        headers=org["scim"],
    ).json()
    assert back["active"] is True
    with client.factory() as db:
        assert db.query(Membership).filter_by(user_id=uuid.UUID(u["id"])).count() == 1


def test_delete_deprovisions_and_ends_sessions_immediately(client, org):
    # a real user the IdP provisions, who also has a password session in the meantime
    h = register_and_login(client, "carl@corp.example")
    carl = client.post(f"{S}/Users", json={"userName": "carl@corp.example"}, headers=org["scim"])
    assert carl.status_code == 201  # an existing account is linked, not duplicated
    cid = carl.json()["id"]
    hh = {**h, "X-Org-Id": org["id"]}
    assert client.get(f"{API}/projects", headers=hh).status_code == 200  # member of the org now
    assert client.delete(f"{S}/Users/{cid}", headers=org["scim"]).status_code == 204
    assert client.get(f"{API}/projects", headers=hh).status_code == 403  # no longer a member
    assert client.get(f"{API}/auth/me", headers=h).status_code == 200  # personal org/account stay
    with client.factory() as db:
        assert db.get(User, uuid.UUID(cid)).active is True


def test_sole_org_user_loses_login_and_sessions(client, org):
    u = mk(client, org).json()
    with client.factory() as db:
        user = db.get(User, uuid.UUID(u["id"]))
        from app.utils.security import create_access_token

        tok = create_access_token(str(user.id), user.token_version)
    h = {"Authorization": f"Bearer {tok}", "X-Org-Id": org["id"]}
    assert client.get(f"{API}/auth/me", headers=h).status_code == 200
    client.delete(f"{S}/Users/{u['id']}", headers=org["scim"])
    assert client.get(f"{API}/auth/me", headers=h).status_code == 401  # account disabled


def test_the_last_admin_cannot_be_deprovisioned_or_demoted(client, org):
    with client.factory() as db:
        admin = db.query(User).filter_by(email="admin@corp.example").one()
        db.add(ScimIdentity(org_id=uuid.UUID(org["id"]), user_id=admin.id, active=True))
        db.commit()
        aid = str(admin.id)
    r = client.delete(f"{S}/Users/{aid}", headers=org["scim"])
    assert r.status_code == 409 and r.json()["scimType"] == "mutability"
    r = client.patch(
        f"{S}/Groups/viewer",
        json=patch({"op": "add", "path": "members", "value": [{"value": aid}]}),
        headers=org["scim"],
    )
    assert r.status_code == 409


def test_patch_validation(client, org):
    u = mk(client, org).json()
    url = f"{S}/Users/{u['id']}"
    assert client.patch(url, json={"Operations": []}, headers=org["scim"]).status_code == 400
    assert client.patch(url, json=patch({"op": "move"}), headers=org["scim"]).status_code == 400
    r = client.patch(
        url, json=patch({"op": "replace", "path": "title", "value": "x"}), headers=org["scim"]
    )
    assert r.status_code == 400 and r.json()["scimType"] == "invalidPath"
    r = client.patch(
        url,
        json=patch({"op": "replace", "path": "userName", "value": "z@corp.example"}),
        headers=org["scim"],
    )
    assert r.status_code == 400 and r.json()["scimType"] == "mutability"
    r = client.patch(
        url, json=patch({"op": "replace", "path": "active", "value": "maybe"}), headers=org["scim"]
    )
    assert r.status_code == 400
    ok = client.patch(
        url,
        json=patch({"op": "replace", "path": "externalId", "value": "new"}),
        headers=org["scim"],
    )
    assert ok.json()["externalId"] == "new"
    cleared = client.patch(
        url, json=patch({"op": "remove", "path": "externalId"}), headers=org["scim"]
    )
    assert "externalId" not in cleared.json()


def test_unknown_users_are_404_and_other_orgs_users_are_invisible(client, org):
    assert client.get(f"{S}/Users/{uuid.uuid4()}", headers=org["scim"]).status_code == 404
    assert client.get(f"{S}/Users/not-a-uuid", headers=org["scim"]).status_code == 404
    h2 = register_and_login(client, "admin2@other.example")
    o2 = client.get(f"{API}/orgs", headers=h2).json()[0]["id"]
    t2 = client.post(
        f"{API}/orgs/{o2}/scim-tokens", json={"name": "x"}, headers={**h2, "X-Org-Id": o2}
    ).json()["token"]
    other = {"Authorization": f"Bearer {t2}"}
    uid = mk(client, org).json()["id"]
    assert client.get(f"{S}/Users/{uid}", headers=other).status_code == 404
    assert client.delete(f"{S}/Users/{uid}", headers=other).status_code == 404
    assert client.get(f"{S}/Users", headers=other).json()["totalResults"] == 0


def test_revoked_token_stops_working_and_revocation_is_audited(client, org):
    assert client.get(f"{S}/Users", headers=org["scim"]).status_code == 200
    r = client.delete(f"{API}/orgs/{org['id']}/scim-tokens/{org['token_id']}", headers=org["admin"])
    assert r.status_code == 204
    assert client.get(f"{S}/Users", headers=org["scim"]).status_code == 401
    assert (
        client.delete(
            f"{API}/orgs/{org['id']}/scim-tokens/{uuid.uuid4()}", headers=org["admin"]
        ).status_code
        == 404
    )
    with client.factory() as db:
        assert db.query(AuditLog).filter_by(action="scim.token_revoked").count() == 1


def test_a_scim_provisioned_user_is_passwordless_verified_and_holds_the_requested_role(client, org):
    """The provisioned account has no password; the IdP vouched for its address."""
    u = mk(client, org, roles=[{"value": "approver"}]).json()
    with client.factory() as db:
        user = db.get(User, uuid.UUID(u["id"]))
        assert user.password_hash is None and user.email_verified_at is not None
        assert db.query(Membership).filter_by(user_id=user.id).one().role == "approver"
