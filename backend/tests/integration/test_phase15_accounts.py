"""Phase 15: email verification, password reset, invitations, sessions, notifications, quotas."""

import re
import uuid

import pytest
from sqlalchemy import select

from app.config import Settings, settings
from app.database.models import (
    ApprovalRequest,
    EmailToken,
    Membership,
    Notification,
    Organization,
    OrgInvite,
    Task,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.services import mail_service, notification_service, quota_service
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import HAPPY_LLM, run
from tests.integration.test_phase6_controls import FAIL_THEN_PASS

API = "/api/v1"


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "memory")
    mail_service.outbox.clear()
    yield mail_service.outbox
    mail_service.outbox.clear()


def token_from(mail) -> str:
    m = re.search(r"token=([\w-]+)", mail.body)
    assert m, mail.body
    return m.group(1)


def last_mail(mailbox, to=None):
    return [m for m in mailbox if to is None or m.to == to][-1]


def login_tokens(client, email, password="password123"):
    r = client.post(f"{API}/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def org_of(client, h):
    return client.get(f"{API}/orgs", headers=h).json()[0]["id"]


def seed_task(client, h):
    p = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()
    body = {"project_id": p["id"], "requirement": "Build a thing with tests."}
    return client.post(f"{API}/tasks", json=body, headers=h).json()


# ---- email verification ------------------------------------------------------------------


def test_register_sends_a_verification_mail_and_the_link_verifies_once(client, mailbox):
    h = register_and_login(client, "new@example.com")
    assert client.get(f"{API}/auth/me", headers=h).json()["email_verified_at"] is None
    mail = last_mail(mailbox, "new@example.com")
    assert "Verify" in mail.subject
    raw = token_from(mail)
    ok = client.post(f"{API}/auth/verify-email", json={"token": raw})
    assert ok.status_code == 200 and ok.json()["email_verified_at"]
    assert client.get(f"{API}/auth/me", headers=h).json()["email_verified_at"]
    assert client.post(f"{API}/auth/verify-email", json={"token": raw}).status_code == 400


def test_bad_or_expired_verification_tokens_are_refused(client, mailbox):
    register_and_login(client, "exp@example.com")
    raw = token_from(last_mail(mailbox))
    assert client.post(f"{API}/auth/verify-email", json={"token": "x" * 30}).status_code == 400
    with client.factory() as db:
        row = db.scalars(select(EmailToken)).first()
        row.expires_at = row.created_at  # already past
        db.commit()
    assert client.post(f"{API}/auth/verify-email", json={"token": raw}).status_code == 400


def test_tokens_are_stored_hashed_and_a_reset_token_cannot_verify(client, mailbox):
    register_and_login(client, "h@example.com")
    raw = token_from(last_mail(mailbox))
    with client.factory() as db:
        assert all(raw not in t.token_hash for t in db.scalars(select(EmailToken)))
    client.post(f"{API}/auth/password-reset/request", json={"email": "h@example.com"})
    reset = token_from(last_mail(mailbox))
    assert client.post(f"{API}/auth/verify-email", json={"token": reset}).status_code == 400


def test_resend_verification_only_when_unverified(client, mailbox):
    h = register_and_login(client, "r@example.com")
    before = len(mailbox)
    assert client.post(f"{API}/auth/resend-verification", headers=h).status_code == 202
    assert len(mailbox) == before + 1
    client.post(f"{API}/auth/verify-email", json={"token": token_from(last_mail(mailbox))})
    assert client.post(f"{API}/auth/resend-verification", headers=h).status_code == 202
    assert len(mailbox) == before + 1  # nothing more sent


# ---- password reset ----------------------------------------------------------------------


def test_reset_answers_identically_for_known_and_unknown_addresses(client, mailbox):
    register_and_login(client, "known@example.com")
    mailbox.clear()
    a = client.post(f"{API}/auth/password-reset/request", json={"email": "known@example.com"})
    b = client.post(f"{API}/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert a.status_code == b.status_code == 202
    assert a.json() == b.json()
    assert [m.to for m in mailbox] == ["known@example.com"]  # only the real one got mail


def test_reset_changes_the_password_ends_all_sessions_and_works_once(client, mailbox):
    register_and_login(client, "pw@example.com")
    old = login_tokens(client, "pw@example.com")
    client.post(f"{API}/auth/password-reset/request", json={"email": "pw@example.com"})
    raw = token_from(last_mail(mailbox))
    body = {"token": raw, "password": "brandnew456"}
    assert client.post(f"{API}/auth/password-reset/confirm", json=body).status_code == 204
    assert client.get(f"{API}/auth/me", headers=bearer(old)).status_code == 401
    refresh = client.post(f"{API}/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert refresh.status_code == 401
    form = {"username": "pw@example.com", "password": "password123"}
    assert client.post(f"{API}/auth/login", data=form).status_code == 401
    new = login_tokens(client, "pw@example.com", "brandnew456")
    again = {"token": raw, "password": "another789x"}
    assert client.post(f"{API}/auth/password-reset/confirm", json=again).status_code == 400
    assert client.get(f"{API}/auth/me", headers=bearer(new)).json()["email_verified_at"]


def test_reset_requests_are_rate_limited_silently(client, mailbox):
    register_and_login(client, "spam@example.com")
    mailbox.clear()
    for _ in range(settings.login_max_attempts + 3):
        r = client.post(f"{API}/auth/password-reset/request", json={"email": "spam@example.com"})
        assert r.status_code == 202
    assert len(mailbox) == settings.login_max_attempts  # the rest were swallowed, same reply


def test_reset_enforces_password_complexity(client, mailbox):
    register_and_login(client, "c@example.com")
    client.post(f"{API}/auth/password-reset/request", json={"email": "c@example.com"})
    body = {"token": token_from(last_mail(mailbox)), "password": "allletters"}
    assert client.post(f"{API}/auth/password-reset/confirm", json=body).status_code == 422


# ---- sessions ----------------------------------------------------------------------------


def test_sessions_list_marks_current_and_revoke_kills_that_session(client):
    register_and_login(client, "s@example.com")
    a = login_tokens(client, "s@example.com")
    login_tokens(client, "s@example.com")
    rows = client.get(
        f"{API}/auth/sessions", headers={**bearer(a), "X-Refresh-Token": a["refresh_token"]}
    ).json()
    assert len(rows) >= 2 and sum(r["current"] for r in rows) == 1
    other = next(r for r in rows if not r["current"])
    url = f"{API}/auth/sessions/{other['family_id']}"
    assert client.delete(url, headers=bearer(a)).status_code == 204
    assert client.delete(url, headers=bearer(a)).status_code == 404
    missing = f"{API}/auth/sessions/{uuid.uuid4()}"
    assert client.delete(missing, headers=bearer(a)).status_code == 404
    refreshed = client.post(f"{API}/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert refreshed.status_code == 200  # our own session is untouched


def test_one_user_cannot_revoke_another_users_session(client):
    register_and_login(client, "u1@example.com")
    register_and_login(client, "u2@example.com")
    t1, t2 = login_tokens(client, "u1@example.com"), login_tokens(client, "u2@example.com")
    fam = client.get(f"{API}/auth/sessions", headers=bearer(t1)).json()[0]["family_id"]
    assert client.delete(f"{API}/auth/sessions/{fam}", headers=bearer(t2)).status_code == 404


def test_session_metadata_is_recorded_and_survives_rotation(client):
    register_and_login(client, "m@example.com")
    r = client.post(
        f"{API}/auth/login",
        data={"username": "m@example.com", "password": "password123"},
        headers={"User-Agent": "TestBrowser/1.0"},
    ).json()
    client.post(f"{API}/auth/refresh", json={"refresh_token": r["refresh_token"]})
    rows = client.get(f"{API}/auth/sessions", headers=bearer(r)).json()
    assert any(s["user_agent"] == "TestBrowser/1.0" for s in rows)


# ---- invitations -------------------------------------------------------------------------


def verify_latest(client, mailbox, email):
    client.post(f"{API}/auth/verify-email", json={"token": token_from(last_mail(mailbox, email))})


def test_invite_flow_for_an_unregistered_address(client, mailbox):
    admin = register_and_login(client, "boss@example.com")
    org = org_of(client, admin)
    body = {"email": "newbie@example.com", "role": "approver"}
    assert client.post(f"{API}/orgs/{org}/invites", json=body, headers=admin).status_code == 202
    raw = token_from(last_mail(mailbox, "newbie@example.com"))
    pending = client.get(f"{API}/orgs/{org}/invites", headers=admin).json()
    assert [p["email"] for p in pending] == ["newbie@example.com"]
    new = register_and_login(client, "newbie@example.com")
    blocked = client.post(f"{API}/invites/accept", json={"token": raw}, headers=new)
    assert blocked.status_code == 400 and "Verify" in blocked.json()["error"]["message"]
    verify_latest(client, mailbox, "newbie@example.com")
    ok = client.post(f"{API}/invites/accept", json={"token": raw}, headers=new)
    assert ok.status_code == 200 and ok.json() == {"org_id": org, "role": "approver"}
    orgs = {o["id"]: o["role"] for o in client.get(f"{API}/orgs", headers=new).json()}
    assert orgs[org] == "approver"
    assert client.post(f"{API}/invites/accept", json={"token": raw}, headers=new).status_code == 400
    assert client.get(f"{API}/orgs/{org}/invites", headers=admin).json() == []


def test_invite_reply_does_not_reveal_whether_the_address_exists(client, mailbox):
    admin = register_and_login(client, "a@example.com")
    register_and_login(client, "exists@example.com")
    org = org_of(client, admin)
    url = f"{API}/orgs/{org}/invites"
    a = client.post(url, json={"email": "exists@example.com"}, headers=admin)
    b = client.post(url, json={"email": "nobody@example.com"}, headers=admin)
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    mailbox.clear()
    again = client.post(url, json={"email": "a@example.com"}, headers=admin)  # already a member
    assert again.json() == a.json() and mailbox == []


def test_invite_for_a_different_address_revoked_and_expired(client, mailbox):
    admin = register_and_login(client, "adm@example.com")
    org = org_of(client, admin)
    url = f"{API}/orgs/{org}/invites"
    client.post(url, json={"email": "target@example.com"}, headers=admin)
    raw = token_from(last_mail(mailbox, "target@example.com"))
    other = register_and_login(client, "other@example.com")
    wrong = client.post(f"{API}/invites/accept", json={"token": raw}, headers=other)
    assert wrong.status_code == 400 and "different email" in wrong.json()["error"]["message"]

    inv_id = client.get(url, headers=admin).json()[0]["id"]
    assert client.delete(f"{url}/{inv_id}", headers=admin).status_code == 204
    assert client.delete(f"{url}/{inv_id}", headers=admin).status_code == 404
    target = register_and_login(client, "target@example.com")
    verify_latest(client, mailbox, "target@example.com")
    revoked = client.post(f"{API}/invites/accept", json={"token": raw}, headers=target)
    assert revoked.status_code == 400

    client.post(url, json={"email": "target@example.com"}, headers=admin)
    raw2 = token_from(last_mail(mailbox, "target@example.com"))
    with client.factory() as db:
        for inv in db.scalars(select(OrgInvite).where(OrgInvite.revoked_at.is_(None))):
            inv.expires_at = inv.created_at
        db.commit()
    expired = client.post(f"{API}/invites/accept", json={"token": raw2}, headers=target)
    assert expired.status_code == 400


def test_a_re_invite_replaces_the_older_link(client, mailbox):
    admin = register_and_login(client, "re@example.com")
    org = org_of(client, admin)
    url = f"{API}/orgs/{org}/invites"
    client.post(url, json={"email": "x@example.com"}, headers=admin)
    first = token_from(last_mail(mailbox, "x@example.com"))
    client.post(url, json={"email": "x@example.com"}, headers=admin)
    assert len(client.get(url, headers=admin).json()) == 1
    user = register_and_login(client, "x@example.com")
    verify_latest(client, mailbox, "x@example.com")
    assert (
        client.post(f"{API}/invites/accept", json={"token": first}, headers=user).status_code == 400
    )


def test_only_admins_invite(client):
    admin = register_and_login(client, "ad@example.com")
    dev = register_and_login(client, "dv@example.com")
    org = org_of(client, admin)
    client.post(f"{API}/orgs/{org}/members", json={"email": "dv@example.com"}, headers=admin)
    r = client.post(
        f"{API}/orgs/{org}/invites",
        json={"email": "z@example.com"},
        headers={**dev, "X-Org-Id": org},
    )
    assert r.status_code == 403


# ---- notifications -----------------------------------------------------------------------


def test_notification_fan_out_dedupe_read_and_email_preference(client, mailbox):
    h = register_and_login(client, "n@example.com")
    org = uuid.UUID(org_of(client, h))
    mailbox.clear()
    with client.factory() as db:
        args = (db, org, "task.completed", "Task finished: x", {"task_id": "t"})
        assert notification_service.notify(*args, roles=("admin",), dedupe_key="k1") == 1
        assert notification_service.notify(*args, roles=("admin",), dedupe_key="k1") == 0
    assert [m.to for m in mailbox] == ["n@example.com"]
    listing = client.get(f"{API}/notifications", headers=h).json()
    assert listing["unread"] == 1 and listing["items"][0]["kind"] == "task.completed"
    nid = listing["items"][0]["id"]
    assert client.post(f"{API}/notifications/{nid}/read", headers=h).status_code == 204
    assert client.get(f"{API}/notifications?unread_only=true", headers=h).json()["unread"] == 0
    assert client.post(f"{API}/notifications/{uuid.uuid4()}/read", headers=h).status_code == 404
    off = client.put(f"{API}/notifications/preferences", json={"notify_email": False}, headers=h)
    assert off.json() == {"notify_email": False}
    mailbox.clear()
    with client.factory() as db:
        notification_service.notify(db, org, "task.failed", "t", {}, roles=("admin",))
    assert mailbox == []  # in-app only now
    assert client.post(f"{API}/notifications/read-all", headers=h).status_code == 204
    assert client.get(f"{API}/notifications/preferences", headers=h).json()["notify_email"] is False


def test_a_user_cannot_read_or_mark_someone_elses_notification(client):
    a = register_and_login(client, "na@example.com")
    b = register_and_login(client, "nb@example.com")
    with client.factory() as db:
        org = uuid.UUID(org_of(client, a))
        notification_service.notify(db, org, "x", "t", {}, roles=("admin",))
    nid = client.get(f"{API}/notifications", headers=a).json()["items"][0]["id"]
    assert client.post(f"{API}/notifications/{nid}/read", headers=b).status_code == 404
    assert client.get(f"{API}/notifications", headers=b).json()["items"] == []


def test_notifications_queue_a_webhook_for_the_event(client):
    h = register_and_login(client, "wh@example.com")
    org = uuid.UUID(org_of(client, h))
    with client.factory() as db:
        db.add(
            WebhookEndpoint(
                org_id=org, url="https://example.com/h", secret="s", events=["approval.needed"]
            )
        )
        db.commit()
        notification_service.notify(db, org, "approval.needed", "Needed", {}, roles=("admin",))
        assert db.scalars(select(WebhookDelivery)).first().event == "approval.needed"


def test_approval_gate_notifies_approvers(client):
    h, _, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM, require_plan_approval=True)
    items = client.get(f"{API}/notifications", headers=h).json()["items"]
    assert [i["kind"] for i in items] == ["approval.needed"]


def test_finished_tasks_notify_their_creator(client):
    h, _, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    kinds = [i["kind"] for i in client.get(f"{API}/notifications", headers=h).json()["items"]]
    assert "task.completed" in kinds


# ---- quotas ------------------------------------------------------------------------------


def two_member_org(client):
    admin = register_and_login(client, "qa@example.com")
    dev = register_and_login(client, "qd@example.com")
    org = org_of(client, admin)
    client.post(f"{API}/orgs/{org}/members", json={"email": "qd@example.com"}, headers=admin)
    return org, {**admin, "X-Org-Id": org}, {**dev, "X-Org-Id": org}


def user_id(client, h):
    return client.get(f"{API}/auth/me", headers=h).json()["id"]


def test_member_task_quota_blocks_only_that_member(client):
    org, admin, dev = two_member_org(client)
    url = f"{API}/orgs/{org}/members/{user_id(client, dev)}/quota"
    r = client.put(url, json={"max_tasks_month": 1}, headers=admin)
    assert r.status_code == 200 and r.json()["max_tasks_month"] == 1
    assert seed_task(client, dev)["status"] == "PENDING"
    p = client.post(f"{API}/projects", json={"name": "p2"}, headers=dev).json()
    body = {"project_id": p["id"], "requirement": "Another task, please."}
    blocked = client.post(f"{API}/tasks", json=body, headers=dev)
    assert blocked.status_code == 429
    assert "your monthly task quota" in blocked.json()["error"]["message"]
    assert seed_task(client, admin)["status"] == "PENDING"  # the admin has no personal cap
    mine = client.get(f"{API}/orgs/{org}/my-usage", headers=dev).json()
    assert mine["member"]["tasks_created"] == 1 and mine["member"]["tasks_remaining"] == 0
    assert mine["org"]["tasks_created"] == 2
    assert {"scope": "member", "resource": "tasks", "used": 1, "cap": 1} in mine["warnings"]


def test_ceiling_is_the_lower_of_org_and_member_remainders(client):
    org, admin, dev = two_member_org(client)
    task = seed_task(client, dev)
    url = f"{API}/orgs/{org}/members/{user_id(client, dev)}/quota"
    client.put(url, json={"token_quota_month": 500}, headers=admin)
    client.patch(f"{API}/orgs/{org}", json={"token_quota_month": 10_000}, headers=admin)
    with client.factory() as db:
        t = db.get(Task, uuid.UUID(task["id"]))
        assert quota_service.token_ceiling(db, t, 0) == 500
        db.get(Organization, uuid.UUID(org)).token_quota_month = 200
        db.commit()
        assert quota_service.token_ceiling(db, t, 0) == 200


def test_member_token_quota_blocks_start(client):
    org, admin, dev = two_member_org(client)
    task = seed_task(client, dev)
    url = f"{API}/orgs/{org}/members/{user_id(client, dev)}/quota"
    client.put(url, json={"token_quota_month": 0}, headers=admin)
    with client.factory() as db:
        from app.database.models import AgentRun, Iteration

        it = Iteration(task_id=uuid.UUID(task["id"]), iteration_number=1)
        db.add(it)
        db.flush()
        db.add(AgentRun(iteration_id=it.id, agent_name="Planner", tokens_used=5))
        db.commit()
    r = client.post(f"{API}/tasks/{task['id']}/start", headers=dev)
    assert r.status_code == 429 and "your monthly token quota" in r.json()["error"]["message"]


def test_quota_near_limit_warns_once_per_month(client):
    org, admin, dev = two_member_org(client)
    client.patch(f"{API}/orgs/{org}", json={"max_tasks_month": 2}, headers=admin)
    seed_task(client, dev)  # 1 of 2 = 50%
    assert client.get(f"{API}/notifications", headers=admin).json()["items"] == []
    seed_task(client, dev)  # 2 of 2 = 100% >= 80%
    kinds = [i["kind"] for i in client.get(f"{API}/notifications", headers=admin).json()["items"]]
    assert kinds == ["quota.near_limit"]
    with client.factory() as db:  # a repeat check in the same month does not repeat the alert
        notification_service.check_quota_warnings(db, uuid.UUID(org), None)
    assert len(client.get(f"{API}/notifications", headers=admin).json()["items"]) == 1


def test_member_quota_validation_and_audit(client):
    org, admin, dev = two_member_org(client)
    url = f"{API}/orgs/{org}/members/{user_id(client, dev)}/quota"
    assert client.put(url, json={"max_tasks_month": -1}, headers=admin).status_code == 422
    other = f"{API}/orgs/{org}/members/{uuid.uuid4()}/quota"
    assert client.put(other, json={}, headers=admin).status_code == 404
    client.put(url, json={"max_tasks_month": 3}, headers=admin)
    actions = [a["action"] for a in client.get(f"{API}/orgs/{org}/audit", headers=admin).json()]
    assert "member.quota_change" in actions


# ---- guided experience -------------------------------------------------------------------


def test_templates_and_onboarding(client, mailbox):
    h = register_and_login(client, "g@example.com")
    templates = client.get(f"{API}/templates", headers=h).json()
    assert {t["id"] for t in templates} == {"crud-api", "auth-service", "validation-library"}
    first = client.get(f"{API}/me/onboarding", headers=h).json()
    assert first["complete"] is False and not any(s["done"] for s in first["steps"])
    seed_task(client, h)
    verify_latest(client, mailbox, "g@example.com")
    steps = client.get(f"{API}/me/onboarding", headers=h).json()["steps"]
    done = {s["id"]: s["done"] for s in steps}
    assert done["first_task"] and done["verify_email"] and not done["first_result"]


def test_approval_comments_roundtrip_and_authz(client):
    admin = register_and_login(client, "cm@example.com")
    org = org_of(client, admin)
    viewer = register_and_login(client, "cv@example.com")
    member = {"email": "cv@example.com", "role": "viewer"}
    client.post(f"{API}/orgs/{org}/members", json=member, headers=admin)
    ha, hv = {**admin, "X-Org-Id": org}, {**viewer, "X-Org-Id": org}
    task = seed_task(client, ha)
    with client.factory() as db:
        req = ApprovalRequest(
            task_id=uuid.UUID(task["id"]), kind="plan", summary="s", resume_status="PLANNING"
        )
        db.add(req)
        db.commit()
        rid = req.id
    url = f"{API}/tasks/{task['id']}/approvals/{rid}/comments"
    c = client.post(url, json={"file_path": "app/x.py", "line": 3, "body": "Why?"}, headers=ha)
    assert c.status_code == 201 and c.json()["author"] == "cm@example.com"
    assert client.post(url, json={"body": "nope"}, headers=hv).status_code == 403
    listed = client.get(url, headers=hv).json()
    assert [(x["file_path"], x["line"], x["body"]) for x in listed] == [("app/x.py", 3, "Why?")]
    assert client.post(url, json={"body": ""}, headers=ha).status_code == 422
    nope = f"{API}/tasks/{task['id']}/approvals/{uuid.uuid4()}/comments"
    assert client.get(nope, headers=ha).status_code == 404


def test_failure_explanation_in_report_for_an_escalated_task(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM, token_budget=1000)
    fe = client.get(f"{API}/tasks/{tid}/report", headers=h).json()["failure_explanation"]
    assert fe and fe["what_failed"] and fe["next_steps"]
    assert "Nothing in this task is accepted" in fe["next_steps"][-1]
    md = client.get(f"{API}/tasks/{tid}/report.md", headers=h).text
    assert "Why it was not accepted" in md and "What a person should do" in md


def test_accepted_tasks_have_no_failure_explanation(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    assert client.get(f"{API}/tasks/{tid}/report", headers=h).json()["failure_explanation"] is None


# ---- configuration and mail --------------------------------------------------------------


def test_production_requires_smtp():
    base = {
        "environment": "production",
        "jwt_secret": "x" * 40,
        "llm_provider": "openai",
        "sandbox_backend": "docker",
        "mail_backend": "console",
    }
    with pytest.raises(ValueError, match="MAIL_BACKEND"):
        Settings(**base)
    assert Settings(**{**base, "mail_backend": "smtp"}).mail_backend == "smtp"


def test_mail_failures_never_raise(monkeypatch):
    def boom(_mail):
        raise OSError("down")

    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(mail_service, "_smtp_send", boom)
    assert mail_service.send("a@b.c", "s", "b") is False


def test_console_backend_only_logs(monkeypatch):
    seen = []
    monkeypatch.setattr(settings, "mail_backend", "console")
    monkeypatch.setattr(mail_service.log, "info", lambda *a: seen.append(a))
    assert mail_service.send("a@b.c", "Subject", "Body") is True
    assert seen and "Subject" in seen[0]


def test_new_accounts_start_with_defaults(client):
    register_and_login(client, "mh@example.com")
    with client.factory() as db:
        assert db.scalars(select(Membership)).first().role == "admin"
        assert db.scalars(select(Notification)).first() is None
