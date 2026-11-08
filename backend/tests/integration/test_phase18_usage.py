# ruff: noqa: E501
"""Phase 18: usage reports (JSON + CSV), plans, and the operator CLI."""

import csv
import io
import json
import uuid
from datetime import datetime, timedelta

import pytest

from app import ops_cli
from app.config import Settings, settings
from app.database.models import AgentRun, Iteration, Organization, Project, Task
from app.services import plans, quota_service, usage_service
from tests.conftest import register_and_login

API = "/api/v1"


@pytest.fixture
def org(client):
    h = register_and_login(client, "owner@x.com")
    oid = client.get(f"{API}/orgs", headers=h).json()[0]["id"]
    return {"id": oid, "h": {**h, "X-Org-Id": oid}}


def seed(
    client, org, project="alpha", runs=(("Builder", "m-a", 1000, 2.0),), when=None, email=None
):
    """Insert a task with agent runs directly (usage is derived from stored rows)."""
    with client.factory() as db:
        proj = db.query(Project).filter_by(name=project, org_id=uuid.UUID(org["id"])).first()
        if proj is None:
            proj = Project(
                name=project,
                org_id=uuid.UUID(org["id"]),
                user_id=db.query(Organization).first().memberships[0].user_id,
            )
            db.add(proj)
            db.flush()
        task = Task(project_id=proj.id, requirement="Build it please now", created_by=proj.user_id)
        db.add(task)
        db.flush()
        it = Iteration(task_id=task.id, iteration_number=1)
        db.add(it)
        db.flush()
        for agent, model, tokens, secs in runs:
            db.add(AgentRun(iteration_id=it.id, agent_name=agent, model=model, tokens_used=tokens,
                            duration_seconds=secs, started_at=when or datetime.utcnow()))  # fmt: skip
        db.commit()
        return str(task.id)


def report(client, org, **params):
    return client.get(f"{API}/orgs/{org['id']}/usage/report", params=params, headers=org["h"])


def test_report_groups_tokens_cost_and_time_and_totals_add_up(client, org, monkeypatch):
    monkeypatch.setattr(settings, "model_prices_json", json.dumps({"m-a": 0.01, "m-b": 0.03}))
    seed(client, org, "alpha", [("Builder", "m-a", 1000, 2.0), ("Reviewer", "m-b", 2000, 3.0)])
    seed(client, org, "beta", [("Builder", "m-a", 500, 1.0)])
    by_project = report(client, org, group_by="project").json()
    rows = {r["label"]: r for r in by_project["rows"]}
    assert (
        rows["alpha"]["tokens"] == 3000
        and rows["alpha"]["agent_runs"] == 2
        and rows["alpha"]["tasks"] == 1
    )
    assert rows["alpha"]["estimated_cost_usd"] == pytest.approx(1 * 0.01 + 2 * 0.03)
    assert rows["beta"]["agent_seconds"] == 1.0
    assert by_project["totals"] == {
        "tasks": 2, "agent_runs": 3, "tokens": 3500,
        "estimated_cost_usd": pytest.approx(0.01 + 0.06 + 0.005), "agent_seconds": 6.0,
    }  # fmt: skip
    assert "estimate" in by_project["note"]
    for group in ("member", "agent", "model", "day"):
        data = report(client, org, group_by=group).json()
        assert data["totals"]["tokens"] == 3500, group  # every grouping partitions the same usage
    agents = {r["label"] for r in report(client, org, group_by="agent").json()["rows"]}
    assert agents == {"Builder", "Reviewer"}
    assert report(client, org, group_by="member").json()["rows"][0]["label"] == "owner@x.com"


def test_period_filters_and_validation(client, org):
    old = datetime.utcnow() - timedelta(days=90)
    seed(client, org, "old", [("Builder", "m", 100, 1.0)], when=old)
    seed(client, org, "new", [("Builder", "m", 700, 1.0)])
    assert report(client, org).json()["totals"]["tokens"] == 700  # default: this month so far
    d = old.date().isoformat()
    only_old = report(client, org, **{"from": d, "to": d}).json()
    assert only_old["totals"]["tokens"] == 100 and only_old["period"] == {"from": d, "to": d}
    assert report(client, org, group_by="nope").status_code == 422
    assert report(client, org, **{"from": "2026-02-02", "to": "2026-02-01"}).status_code == 422
    assert report(client, org, **{"from": "2020-01-01", "to": "2026-01-01"}).status_code == 422
    assert report(client, org, **{"from": "not-a-date"}).status_code == 422
    empty = report(client, org, **{"from": "2001-01-01", "to": "2001-01-02"}).json()
    assert empty["rows"] == [] and empty["totals"]["tokens"] == 0


def test_report_is_scoped_to_the_organization_and_admin_only(client, org):
    seed(client, org, "mine", [("Builder", "m", 123, 1.0)])
    other = register_and_login(client, "other@x.com")
    oo = client.get(f"{API}/orgs", headers=other).json()[0]["id"]
    theirs = client.get(f"{API}/orgs/{oo}/usage/report", headers={**other, "X-Org-Id": oo})
    assert theirs.status_code == 200 and theirs.json()["totals"]["tokens"] == 0
    assert client.get(f"{API}/orgs/{org['id']}/usage/report", headers=other).status_code == 404


def test_csv_export_columns_totals_and_formula_injection(client, org):
    seed(client, org, '=HYPERLINK("http://evil","x")', [("Builder", "m", 10, 1.0)])
    seed(client, org, "plain, with comma", [("Builder", "m", 20, 1.0)])
    r = client.get(
        f"{API}/orgs/{org['id']}/usage/report.csv", params={"group_by": "project"}, headers=org["h"]
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="usage-' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["period_from", "period_to", "group_by", "key"]
    body = {row[4]: row for row in rows[1:-1]}
    assert any(
        k.startswith("'=HYPERLINK") for k in body
    )  # neutralised: stays text in a spreadsheet
    assert not any(k.startswith("=") for k in body)
    assert "plain, with comma" in body  # quoting survives a comma
    total = rows[-1]
    assert total[3] == "TOTAL" and total[7] == "30"
    assert (
        client.get(
            f"{API}/orgs/{org['id']}/usage/report.csv?group_by=zzz", headers=org["h"]
        ).status_code
        == 422
    )


# ---- plans -------------------------------------------------------------------------------------

PLANS = json.dumps(
    {"free": {"token_quota_month": 1000, "max_tasks_month": 2}, "pro": {"max_tasks_month": None}}
)


def test_plan_supplies_default_quotas_and_the_orgs_own_cap_wins(client, org, monkeypatch):
    monkeypatch.setattr(settings, "plans_json", PLANS)
    with client.factory() as db:
        o = db.get(Organization, uuid.UUID(org["id"]))
        assert (plans.token_quota(o), plans.max_tasks(o)) == (
            None,
            None,
        )  # "default" plan: no limits
        o.plan = "free"
        db.commit()
        assert (plans.token_quota(o), plans.max_tasks(o)) == (1000, 2)
        o.token_quota_month = 5000  # explicit org cap beats the plan
        assert plans.token_quota(o) == 5000 and plans.max_tasks(o) == 2
        o.plan = "unknown-plan"
        assert plans.max_tasks(o) is None


def test_plan_limits_are_enforced_through_the_existing_quota_checks(client, org, monkeypatch):
    monkeypatch.setattr(settings, "plans_json", PLANS)
    with client.factory() as db:
        db.get(Organization, uuid.UUID(org["id"])).plan = "free"
        db.commit()
    proj = client.post(f"{API}/projects", json={"name": "p"}, headers=org["h"]).json()
    body = {"project_id": proj["id"], "requirement": "Build employees"}
    assert client.post(f"{API}/tasks", json=body, headers=org["h"]).status_code == 201
    assert client.post(f"{API}/tasks", json=body, headers=org["h"]).status_code == 201
    third = client.post(f"{API}/tasks", json=body, headers=org["h"])
    assert third.status_code == 429 and "task quota reached (2)" in third.json()["error"]["message"]
    usage = client.get(f"{API}/orgs/{org['id']}/usage", headers=org["h"]).json()
    assert (
        usage["max_tasks_month"] == 2
        and usage["tasks_remaining"] == 0
        and usage["token_quota_month"] == 1000
    )
    with client.factory() as db:
        o = db.get(Organization, uuid.UUID(org["id"]))
        assert quota_service.usage(db, o)["token_quota_month"] == 1000


def test_org_admins_cannot_assign_their_own_plan_but_can_see_it(client, org):
    r = client.patch(f"{API}/orgs/{org['id']}", json={"plan": "enterprise"}, headers=org["h"])
    assert r.status_code == 200 and r.json()["plan"] == "default"  # unknown field ignored
    assert client.get(f"{API}/orgs/{org['id']}", headers=org["h"]).json()["plan"] == "default"


@pytest.mark.parametrize(
    "raw",
    [
        "nope",
        "[]",
        json.dumps({"p": {"bogus": 1}}),
        json.dumps({"p": {"max_tasks_month": -1}}),
        json.dumps({"p": {"max_tasks_month": True}}),
        json.dumps({"p": 5}),
    ],
)
def test_bad_plans_are_refused_at_startup(raw):
    with pytest.raises(ValueError, match="PLANS_JSON"):
        Settings(plans_json=raw)
    Settings(plans_json=PLANS)


def test_operator_cli_lists_and_assigns_plans_with_an_audit_row(client, org, monkeypatch, capsys):
    monkeypatch.setattr(settings, "plans_json", PLANS)
    monkeypatch.setattr(ops_cli, "SessionLocal", client.factory)
    slug = client.get(f"{API}/orgs/{org['id']}", headers=org["h"]).json()["slug"]
    assert ops_cli.main(["plans"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert set(listing["plans"]) == {"free", "pro"} and listing["organizations_per_plan"] == {
        "default": 1
    }
    assert ops_cli.main(["set-plan", slug, "free"]) == 0
    assert "default -> free" in capsys.readouterr().out
    assert ops_cli.main(["set-plan", slug, "nonsense"]) == 2
    assert ops_cli.main(["set-plan", "no-such-org", "free"]) == 2
    capsys.readouterr()
    audit = client.get(f"{API}/orgs/{org['id']}/audit", headers=org["h"]).json()
    assert "org.plan_changed" in {a["action"] for a in audit}
    assert usage_service.GROUPS == ("project", "member", "agent", "model", "day")
