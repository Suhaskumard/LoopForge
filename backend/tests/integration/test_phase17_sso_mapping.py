# ruff: noqa: F811  (pytest fixtures imported from another test module)
"""Phase 17: SSO group/domain -> organization role mapping (against the scriptable fake IdP)."""

import json
import urllib.parse
import uuid

import pytest

from app.config import settings
from app.database.models import AuditLog, Membership, Organization, User
from tests.conftest import register_and_login
from tests.integration.test_phase10_oidc import fragment, idp, login  # noqa: F401

API = "/api/v1"


@pytest.fixture
def acme(client, monkeypatch):
    """An org with a human admin; returns (slug, org_id)."""
    h = register_and_login(client, "owner@corp.example")
    org = client.get(f"{API}/orgs", headers=h).json()[0]
    monkeypatch.setattr(settings, "oidc_group_role_map_json", "")
    monkeypatch.setattr(settings, "oidc_domain_org_map_json", "")
    return org["slug"], uuid.UUID(org["id"])


def gmap(slug, **groups):
    return json.dumps({g: {"org": slug, "role": r} for g, r in groups.items()})


def sso_user_role(client, org_id):
    with client.factory() as db:
        user = db.query(User).filter(User.email == "sso.user@corp.example").one()
        m = db.query(Membership).filter_by(org_id=org_id, user_id=user.id).first()
        return None if m is None else (m.role, m.source)


def test_groups_grant_the_highest_matching_role_as_sso_source(client, idp, acme, monkeypatch):
    slug, org = acme
    monkeypatch.setattr(
        settings, "oidc_group_role_map_json", gmap(slug, eng="developer", ops="approver")
    )
    idp.claims = {"groups": ["eng", "ops", "unrelated"]}
    fragment(login(client, idp))
    assert sso_user_role(client, org) == ("approver", "sso")
    with client.factory() as db:
        assert db.query(AuditLog).filter_by(action="sso.member_added", org_id=org).count() == 1


def test_a_later_login_follows_group_changes_both_ways(client, idp, acme, monkeypatch):
    slug, org = acme
    monkeypatch.setattr(
        settings, "oidc_group_role_map_json", gmap(slug, eng="developer", ops="approver")
    )
    idp.claims = {"groups": ["ops"]}
    fragment(login(client, idp, "c1"))
    idp.claims = {"groups": ["eng"]}  # demoted at the IdP
    fragment(login(client, idp, "c2"))
    assert sso_user_role(client, org) == ("developer", "sso")
    idp.claims = {"groups": []}  # left every mapped group: access removed
    fragment(login(client, idp, "c3"))
    assert sso_user_role(client, org) is None
    with client.factory() as db:
        actions = {a.action for a in db.query(AuditLog).filter_by(org_id=org)}
    assert {"sso.member_added", "sso.role_changed", "sso.member_removed"} <= actions


def test_manual_memberships_are_never_touched_by_sso(client, idp, acme, monkeypatch):
    slug, org = acme
    fragment(login(client, idp, "c1"))  # creates the user (no mapping yet)
    with client.factory() as db:
        user = db.query(User).filter(User.email == "sso.user@corp.example").one()
        db.add(Membership(org_id=org, user_id=user.id, role="viewer", source="manual"))
        db.commit()
    monkeypatch.setattr(settings, "oidc_group_role_map_json", gmap(slug, boss="admin"))
    idp.claims = {"groups": ["boss"]}
    fragment(login(client, idp, "c2"))
    assert sso_user_role(client, org) == ("viewer", "manual")


def test_the_last_admin_is_never_demoted_or_removed_by_sso(client, idp, acme, monkeypatch):
    slug, org = acme
    with client.factory() as db:  # the human owner leaves; the SSO user becomes the only admin
        db.query(Membership).filter_by(org_id=org).delete()
        db.commit()
    monkeypatch.setattr(settings, "oidc_group_role_map_json", gmap(slug, boss="admin"))
    idp.claims = {"groups": ["boss"]}
    fragment(login(client, idp, "c1"))
    assert sso_user_role(client, org) == ("admin", "sso")
    idp.claims = {"groups": []}
    fragment(login(client, idp, "c2"))
    assert sso_user_role(client, org) == ("admin", "sso")  # protected
    with client.factory() as db:
        skipped = db.query(AuditLog).filter_by(action="sso.change_skipped", org_id=org).one()
        assert skipped.detail["reason"] == "last admin"


def test_domain_mapping_gives_a_baseline_role(client, idp, acme, monkeypatch):
    slug, org = acme
    monkeypatch.setattr(
        settings,
        "oidc_domain_org_map_json",
        json.dumps({"corp.example": {"org": slug, "role": "viewer"}}),
    )
    monkeypatch.setattr(settings, "oidc_group_role_map_json", gmap(slug, eng="developer"))
    fragment(login(client, idp, "c1"))
    assert sso_user_role(client, org) == ("viewer", "sso")
    idp.claims = {"groups": ["eng"]}
    fragment(login(client, idp, "c2"))
    assert sso_user_role(client, org) == ("developer", "sso")


def test_a_single_string_group_claim_and_unknown_orgs_are_handled(client, idp, acme, monkeypatch):
    slug, org = acme
    raw = json.dumps(
        {"eng": {"org": slug, "role": "developer"}, "x": {"org": "no-such-org", "role": "admin"}}
    )
    monkeypatch.setattr(settings, "oidc_group_role_map_json", raw)
    idp.claims = {"groups": "eng"}  # some IdPs send a bare string
    fragment(login(client, idp))
    assert sso_user_role(client, org) == ("developer", "sso")
    with client.factory() as db:
        assert db.query(Organization).filter_by(slug="no-such-org").count() == 0


def test_without_mapping_nothing_changes(client, idp, acme):
    slug, org = acme
    idp.claims = {"groups": ["anything"]}
    fragment(login(client, idp))
    assert sso_user_role(client, org) is None


@pytest.mark.parametrize(
    "raw",
    [
        "nope",
        "[]",
        json.dumps({"g": {"org": "a", "role": "god"}}),
        json.dumps({"g": {"role": "admin"}}),
        json.dumps({"g": "admin"}),
    ],
)
def test_bad_mapping_is_refused_at_startup(raw):
    from app.config import Settings

    with pytest.raises(ValueError, match="OIDC_GROUP_ROLE_MAP_JSON"):
        Settings(oidc_group_role_map_json=raw)
    with pytest.raises(ValueError, match="OIDC_DOMAIN_ORG_MAP_JSON"):
        Settings(oidc_domain_org_map_json=raw)


def test_a_deactivated_account_cannot_sign_in_through_sso(client, idp, acme):
    fragment(login(client, idp, "c1"))
    with client.factory() as db:
        db.query(User).filter(User.email == "sso.user@corp.example").update({"active": False})
        db.commit()
    r = login(client, idp, "c2")
    assert "disabled" in urllib.parse.unquote_plus(r.headers["location"])
    assert "access_token" not in r.headers["location"]
