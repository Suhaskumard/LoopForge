"""Phase 5 exit gate: KPI values match figures computed directly from the database.

`raw_kpis` recomputes every KPI with plain SQL, independently of analytics_service, and the
tests assert both agree. The scenarios are driven through the real API with the fake LLM and a
scripted sandbox, exactly like the Phase 4 loop tests.
"""

import io
import zipfile
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Iteration, TestResult
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import (
    HAPPY_LLM,
    failing_update_report,
    passing_report_for_demo,
    run,
)

API = "/api/v1"


def raw_kpis(engine, user_email: str) -> dict:
    """KPIs from SQL alone (no ORM, no analytics_service)."""
    with engine.connect() as c:
        q = lambda sql, **p: c.execute(text(sql), p).scalar()  # noqa: E731
        owner = (
            "FROM tasks t JOIN projects p ON p.id = t.project_id "
            "JOIN users u ON u.id = p.user_id WHERE u.email = :e"
        )
        done = q(f"SELECT COUNT(*) {owner} AND t.status = 'COMPLETED'", e=user_email)
        eligible = q(
            f"SELECT COUNT(*) {owner} AND t.status IN ('COMPLETED','FAILED','ESCALATED')",
            e=user_email,
        )
        iters = q(
            "SELECT COUNT(*) FROM iterations i JOIN tasks t ON t.id = i.task_id "
            "JOIN projects p ON p.id = t.project_id JOIN users u ON u.id = p.user_id "
            "WHERE u.email = :e AND t.status = 'COMPLETED'",
            e=user_email,
        )
        # latest test_results row per iteration
        latest = (
            "SELECT r.* FROM test_results r JOIN iterations i ON i.id = r.iteration_id "
            "JOIN tasks t ON t.id = i.task_id JOIN projects p ON p.id = t.project_id "
            "JOIN users u ON u.id = p.user_id WHERE u.email = :e AND r.created_at = "
            "(SELECT MAX(r2.created_at) FROM test_results r2 "
            "WHERE r2.iteration_id = r.iteration_id)"
        )
        executed = q(f"SELECT COALESCE(SUM(total_tests),0) FROM ({latest}) x", e=user_email)
        passed = q(f"SELECT COALESCE(SUM(passed),0) FROM ({latest}) x", e=user_email)
        tokens = q(
            "SELECT COALESCE(SUM(a.tokens_used),0) FROM agent_runs a "
            "JOIN iterations i ON i.id = a.iteration_id JOIN tasks t ON t.id = i.task_id "
            "JOIN projects p ON p.id = t.project_id JOIN users u ON u.id = p.user_id "
            "WHERE u.email = :e",
            e=user_email,
        )
    return {
        "success_rate": round(done * 100 / eligible, 2) if eligible else None,
        "avg_iterations": round(iters / done, 3) if done else None,
        "pass_rate": round(passed * 100 / executed, 2) if executed else None,
        "executed": executed,
        "tokens": tokens,
    }


def overview(client, h) -> dict:
    r = client.get(f"{API}/analytics/overview", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def run_repaired(client, email="kpi@x.com"):
    return run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM, email=email)


def test_empty_account_reports_none_not_fake_zeros(client):
    h = register_and_login(client, "empty@x.com")
    o = overview(client, h)
    assert o["tasks_total"] == 0
    for key in (
        "task_success_rate",
        "average_iterations",
        "test_pass_rate",
        "average_quality_score",
        "average_execution_seconds",
        "average_cost",
    ):
        assert o[key] is None, key
    assert o["recent_tasks"] == []


def test_kpis_match_independent_sql_recomputation(client):
    h, tid, _ = run_repaired(client)
    o = overview(client, h)
    raw = raw_kpis(client.engine, "kpi@x.com")

    assert o["completed"] == 1 and o["task_success_rate"] == raw["success_rate"] == 100.0
    assert o["average_iterations"] == raw["avg_iterations"] == 2.0
    assert o["test_pass_rate"] == raw["pass_rate"]
    assert o["tests_executed"] == raw["executed"] and raw["executed"] > 0
    assert o["total_tokens"] == raw["tokens"] > 0
    assert o["total_cost"] == round(raw["tokens"] / 1000 * settings.cost_per_1k_tokens, 6)
    assert o["average_quality_score"] is not None
    assert o["average_execution_seconds"] is not None and o["average_execution_seconds"] >= 0
    assert o["cost_is_estimate"] is True


def test_cancelled_and_unfinished_tasks_do_not_move_the_success_rate(client):
    h, tid, _ = run_repaired(client)
    before = overview(client, h)
    _, cancelled = new_task_for(client, h)
    assert client.post(f"{API}/tasks/{cancelled}/status", json={"status": "CANCELLED"}, headers=h)
    _, pending = new_task_for(client, h)
    after = overview(client, h)
    assert after["tasks_total"] == before["tasks_total"] + 2
    assert after["task_success_rate"] == before["task_success_rate"] == 100.0
    assert after["eligible_finished"] == before["eligible_finished"] == 1
    assert after["tasks_by_status"]["CANCELLED"] == 1 and after["tasks_by_status"]["PENDING"] == 1


def new_task_for(client, h):
    p = client.post(f"{API}/projects", json={"name": "extra"}, headers=h).json()
    t = client.post(
        f"{API}/tasks", json={"project_id": p["id"], "requirement": "Another one"}, headers=h
    ).json()
    return h, t["id"]


def test_failed_task_counts_against_success_rate(client):
    h, _, _ = run_repaired(client)
    _, tid = new_task_for(client, h)
    for status in ("PLANNING", "FAILED"):
        r = client.post(f"{API}/tasks/{tid}/status", json={"status": status}, headers=h)
        assert r.status_code == 200, r.text
    o = overview(client, h)
    assert o["eligible_finished"] == 2 and o["completed"] == 1
    assert o["task_success_rate"] == raw_kpis(client.engine, "kpi@x.com")["success_rate"] == 50.0


def test_repeated_test_runs_are_not_double_counted(client):
    h, tid, _ = run_repaired(client)
    before = overview(client, h)
    with Session(client.engine) as s:
        it = s.query(Iteration).filter_by(iteration_number=2).one()
        latest = max(it.test_results, key=lambda r: r.created_at)
        # a re-run of the same iteration stores another row; only the newest may count
        s.add(
            TestResult(
                iteration_id=it.id,
                total_tests=latest.total_tests,
                passed=latest.passed,
                failed=latest.failed,
                created_at=latest.created_at + timedelta(seconds=5),
            )
        )
        s.commit()
    after = overview(client, h)
    assert after["tests_executed"] == before["tests_executed"]
    assert after["test_pass_rate"] == before["test_pass_rate"]
    assert after["tests_executed"] == raw_kpis(client.engine, "kpi@x.com")["executed"]


def test_failure_distribution_and_repair_outcomes(client):
    h, tid, _ = run_repaired(client)
    o = overview(client, h)
    assert sum(o["failure_distribution"].values()) == 1
    (category,) = o["failure_distribution"]
    assert o["repair_outcomes"][category] == {"resolved": 1}


def test_task_analytics_shows_the_quality_trend_and_tokens(client):
    h, tid, _ = run_repaired(client)
    r = client.get(f"{API}/analytics/tasks/{tid}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [i["number"] for i in body["iterations"]] == [1, 2]
    assert body["iterations"][0]["tests_failed"] == 1 and body["iterations"][1]["tests_failed"] == 0
    assert body["total_tokens"] == sum(i["tokens"] for i in body["iterations"]) > 0
    assert len(body["quality_trend"]) == 2
    assert body["execution_seconds"] is not None


def test_iteration_analytics_breaks_down_agents(client):
    h, tid, _ = run_repaired(client)
    its = client.get(f"{API}/tasks/{tid}/iterations", headers=h).json()
    r = client.get(f"{API}/analytics/iterations/{its[0]['id']}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert {a["agent"] for a in body["agents"]} >= {"Planner", "Builder", "Verifier"}
    assert body["tests"]["failed"] == 1
    assert body["total_tokens"] == sum(a["tokens"] for a in body["agents"])


def test_agent_analytics_and_status(client):
    h, _, _ = run_repaired(client)
    rows = client.get(f"{API}/analytics/agents", headers=h).json()
    by = {r["agent"]: r for r in rows}
    assert set(by) == {"Planner", "Builder", "Verifier", "Reviewer", "Repair", "Documentation"}
    assert by["Planner"]["runs"] == 1 and by["Planner"]["success_rate"] == 100.0
    assert by["Repair"]["runs"] >= 1
    st = client.get(f"{API}/agents/planner/status", headers=h)
    assert st.status_code == 200 and st.json()["last_status"] == "success"
    assert client.get(f"{API}/agents/nobody/status", headers=h).status_code == 404


def test_analytics_are_owner_scoped(client):
    h, tid, _ = run_repaired(client)
    other = register_and_login(client, "other@x.com")
    assert overview(client, other)["tasks_total"] == 0
    assert all(r["runs"] == 0 for r in client.get(f"{API}/analytics/agents", headers=other).json())
    its = client.get(f"{API}/tasks/{tid}/iterations", headers=h).json()
    assert client.get(f"{API}/analytics/tasks/{tid}", headers=other).status_code == 404
    assert (
        client.get(f"{API}/analytics/iterations/{its[0]['id']}", headers=other).status_code == 404
    )
    assert client.get(f"{API}/analytics/overview").status_code == 401


# ---- diff between any two iterations -------------------------------------------------------


def test_diff_against_any_iteration(client):
    h, tid, _ = run_repaired(client)
    its = client.get(f"{API}/tasks/{tid}/iterations", headers=h).json()
    one, two = its[0]["id"], its[1]["id"]

    default = client.get(f"{API}/iterations/{two}/diff", headers=h).json()
    explicit = client.get(f"{API}/iterations/{two}/diff", params={"against": one}, headers=h).json()
    assert default == explicit and explicit["against"] == 1
    paths = {f["path"]: f for f in explicit["files"]}
    assert "app/routes.py" in paths and "employee_id + 1" in paths["app/routes.py"]["diff"]

    reverse = client.get(f"{API}/iterations/{one}/diff", params={"against": two}, headers=h).json()
    assert reverse["against"] == 2
    assert [f["path"] for f in reverse["files"]] == [f["path"] for f in explicit["files"]]

    same = client.get(f"{API}/iterations/{two}/diff", params={"against": two}, headers=h).json()
    assert same["files"] == []


def test_diff_against_a_foreign_or_unknown_iteration_is_404(client):
    h, tid, _ = run_repaired(client)
    its = client.get(f"{API}/tasks/{tid}/iterations", headers=h).json()
    # a second task of the same user is not a valid comparison base
    run_tid = run_repaired_second(client, h)
    other_its = client.get(f"{API}/tasks/{run_tid}/iterations", headers=h).json()
    r = client.get(
        f"{API}/iterations/{its[1]['id']}/diff", params={"against": other_its[0]["id"]}, headers=h
    )
    assert r.status_code == 404
    bad = "00000000-0000-0000-0000-000000000000"
    assert (
        client.get(f"{API}/iterations/{its[1]['id']}/diff", params={"against": bad}, headers=h)
    ).status_code == 404
    other = register_and_login(client, "spy@x.com")
    assert client.get(f"{API}/iterations/{its[1]['id']}/diff", headers=other).status_code == 404


def run_repaired_second(client, h):
    from app.api.dependencies import get_sandbox
    from app.execution.fake_sandbox import ScriptedSandbox
    from app.main import app

    sandbox = ScriptedSandbox([failing_update_report(), passing_report_for_demo()])
    app.dependency_overrides[get_sandbox] = lambda: sandbox
    client.llm.queue(*HAPPY_LLM)
    _, tid = new_task_for(client, h)
    assert client.post(f"{API}/tasks/{tid}/start", headers=h).status_code == 202
    return tid


# ---- download ------------------------------------------------------------------------------


def test_download_zip_contains_the_latest_iteration_files(client):
    h, tid, _ = run_repaired(client)
    r = client.get(f"{API}/tasks/{tid}/download", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    listed = [f["path"] for f in client.get(f"{API}/tasks/{tid}/files", headers=h).json()]
    assert sorted(names) == sorted(listed) and "requirements.txt" in names


def test_download_requires_ownership_and_files(client):
    h, tid, _ = run_repaired(client)
    other = register_and_login(client, "thief@x.com")
    assert client.get(f"{API}/tasks/{tid}/download", headers=other).status_code == 404
    _, fresh = new_task_for(client, h)
    assert client.get(f"{API}/tasks/{fresh}/download", headers=h).status_code == 404


def test_cors_allows_only_the_configured_origin(client):
    ok = client.options(
        f"{API}/analytics/overview",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        f"{API}/analytics/overview",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_iteration_file_returns_that_iterations_version(client):
    h, tid, _ = run_repaired(client)
    its = client.get(f"{API}/tasks/{tid}/iterations", headers=h).json()
    first = client.get(f"{API}/iterations/{its[0]['id']}/files/app/routes.py", headers=h).json()
    second = client.get(f"{API}/iterations/{its[1]['id']}/files/app/routes.py", headers=h).json()
    assert "employee_id + 1" in first["content"] and "employee_id + 1" not in second["content"]
    assert first["sha256"] != second["sha256"]
    assert (
        client.get(f"{API}/iterations/{its[0]['id']}/files/nope.py", headers=h).status_code == 404
    )
    assert (
        client.get(f"{API}/iterations/{its[0]['id']}/files/../../etc/passwd", headers=h).status_code
        == 404
    )
    other = register_and_login(client, "nosy@x.com")
    assert (
        client.get(
            f"{API}/iterations/{its[0]['id']}/files/app/routes.py", headers=other
        ).status_code
        == 404
    )
