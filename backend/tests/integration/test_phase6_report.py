"""Phase 6.1: final report built from stored evidence + the Documentation Agent."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import AgentRun, Artifact
from app.demo.employee_management import passing_report_for_demo
from app.schemas.report import ReadmeOutput
from app.services import report_service
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import HAPPY_LLM, failing_update_report, new_task, run

API = "/api/v1"
FAIL_THEN_PASS = [failing_update_report(), passing_report_for_demo()]
README = ReadmeOutput(content="# Employee API\n\nRun `uvicorn app.main:app`. Tests: `pytest`.\n")


def report(client, h, tid):
    r = client.get(f"{API}/tasks/{tid}/report", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_report_for_a_repaired_task_tells_the_whole_story(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    r = report(client, h, tid)
    assert r["status"] == "COMPLETED" and r["outcome"].startswith("Accepted")
    assert r["escalation_reason"] is None
    assert [i["number"] for i in r["iterations"]] == [1, 2]
    assert r["iterations"][0]["tests_failed"] == 1 and r["iterations"][1]["tests_failed"] == 0
    assert "app/routes.py" in r["iterations"][1]["repair_files"]
    assert r["tests"]["failed"] == 0 and r["tests"]["total"] > 0
    assert r["total_tokens"] > 0 and r["estimated_cost"] > 0
    assert r["requirements"] and all(
        q["verification_status"] == "verified" for q in r["requirements"]
    )
    assert any(q["implemented_in"] for q in r["requirements"])
    assert {f["path"] for f in r["files"]} >= {"requirements.txt", "app/routes.py"}
    assert r["acceptance_criteria"] and all(c["met"] for c in r["acceptance_criteria"])


def test_report_numbers_match_the_analytics_api(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    r = report(client, h, tid)
    a = client.get(f"{API}/analytics/tasks/{tid}", headers=h).json()
    assert r["total_tokens"] == a["total_tokens"] and r["estimated_cost"] == a["estimated_cost"]


def test_escalated_report_never_claims_success_and_says_why(client):
    h, tid, _ = run(client, [failing_update_report()], HAPPY_LLM, token_budget=1000)
    r = report(client, h, tid)
    assert r["status"] == "ESCALATED"
    assert "NOT accepted" in r["outcome"] and r["escalation_reason"]
    assert "Accepted" not in r["outcome"]


def test_markdown_report_contains_the_evidence(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    res = client.get(f"{API}/tasks/{tid}/report.md", headers=h)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/markdown")
    md = res.text
    for needle in (
        "# LoopForge engineering report",
        "Iteration history",
        "REQ-001",
        "app/routes.py",
    ):
        assert needle in md
    assert "| 1 | failed_tests |" in md and "| 2 | accepted |" in md


def test_report_is_owner_scoped(client):
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    other = register_and_login(client, "peek@x.com")
    assert client.get(f"{API}/tasks/{tid}/report", headers=other).status_code == 404
    assert client.get(f"{API}/tasks/{tid}/report.md", headers=other).status_code == 404
    assert client.get(f"{API}/tasks/{tid}/report").status_code == 401


def test_report_for_a_task_that_never_ran(client):
    h, tid = new_task(client, "idle@x.com")
    r = report(client, h, tid)
    assert r["status"] == "PENDING" and r["iterations"] == [] and r["files"] == []
    assert r["outcome"].startswith("Still in progress")
    assert client.get(f"{API}/tasks/{tid}/report.md", headers=h).status_code == 200


# ---- Documentation Agent --------------------------------------------------------------------


@pytest.fixture
def docs_on(monkeypatch):
    monkeypatch.setattr(settings, "documentation_agent_enabled", True)


def agent_runs(client, tid):
    with Session(client.engine) as s:
        return [r for r in s.scalars(select(AgentRun)) if r.agent_name == "Documentation"]


def test_documentation_agent_writes_a_readme_after_the_task_finishes(client, docs_on):
    h, tid, _ = run(client, FAIL_THEN_PASS, [*HAPPY_LLM, README])
    assert report(client, h, tid)["readme_generated"] is True
    (doc_run,) = agent_runs(client, tid)
    assert doc_run.status == "success" and doc_run.tokens_used > 0
    md = client.get(f"{API}/tasks/{tid}/report.md", headers=h).text
    assert "Generated project README" in md and "uvicorn app.main:app" in md
    with Session(client.engine) as s:
        kinds = {
            a.artifact_type for a in s.scalars(select(Artifact)) if a.file_name.startswith("README")
        }
        assert kinds == {"doc"}  # never mixed into generated source files
    files = [f["path"] for f in client.get(f"{API}/tasks/{tid}/files", headers=h).json()]
    assert "README.generated.md" not in files


def test_documentation_failure_cannot_change_the_verdict(client, docs_on):
    # no README response queued: the agent fails, the task stays COMPLETED, the report still works
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    assert client.get(f"{API}/tasks/{tid}", headers=h).json()["status"] == "COMPLETED"
    r = report(client, h, tid)
    assert r["status"] == "COMPLETED" and r["readme_generated"] is False
    (doc_run,) = agent_runs(client, tid)
    assert doc_run.status == "failed"


def test_documentation_runs_for_escalated_tasks_too(client, docs_on):
    h, tid, _ = run(client, [failing_update_report()], [*HAPPY_LLM[:2], README], max_iterations=1)
    assert client.get(f"{API}/tasks/{tid}", headers=h).json()["status"] == "ESCALATED"
    assert report(client, h, tid)["readme_generated"] is True


def test_documentation_agent_refuses_to_run_before_a_terminal_state(client):
    from app.agents import documenter
    from app.agents.base import AgentContext
    from app.database.models import Iteration, Task
    from app.services.llm_client import FakeLLMClient
    from app.utils.token_tracker import TokenTracker

    h, tid = new_task(client, "early@x.com")
    with client.factory() as db:
        task = db.get(Task, __import__("uuid").UUID(tid))
        ctx = AgentContext(
            db=db,
            task=task,
            iteration=Iteration(),
            llm=FakeLLMClient(),
            tracker=TokenTracker(1000),
        )
        with pytest.raises(RuntimeError, match="terminal"):
            documenter.run(ctx, "{}")


def test_documentation_agent_is_listed_as_implemented(client):
    h = register_and_login(client, "agents@x.com")
    agents = {a["name"]: a for a in client.get(f"{API}/agents", headers=h).json()}
    assert agents["Documentation"]["implemented"] is True


def test_render_markdown_escapes_table_separators():
    import uuid

    from app.schemas.report import FinalReport, ReportRequirement

    r = FinalReport(
        task_id=uuid.uuid4(),
        requirement="x",
        status="COMPLETED",
        outcome="ok",
        escalation_reason=None,
        iterations=[],
        requirements=[
            ReportRequirement(
                req_id="REQ-1",
                description="a | b",
                req_type="functional",
                priority="high",
                implemented_in=[],
                tested_in=[],
                verification_status="verified",
                evidence=None,
            )
        ],
        acceptance_criteria=[],
        tests={"total": 0, "passed": 0, "failed": 0, "coverage": None},
        quality={
            "score": None,
            "lint_findings": 0,
            "high_security_findings": 0,
            "critical_issues": 0,
        },
        files=[],
        total_tokens=0,
        estimated_cost=0.0,
        approvals=[{"kind": "plan", "status": "approved", "summary": "", "iteration": 1}],
        readme_generated=False,
        generated_at="now",
    )
    md = report_service.render_markdown(r)
    assert (
        "a / b" in md and "plan (iteration 1): approved" in md and "No review was recorded." in md
    )


def test_plan_endpoint_survives_repair_iterations(client):
    """Regression: found by the acceptance check. After a repair the LATEST iteration has no plan
    of its own, and GET /plan used to answer 404."""
    h, tid, _ = run(client, FAIL_THEN_PASS, HAPPY_LLM)
    r = client.get(f"{API}/tasks/{tid}/plan", headers=h)
    assert r.status_code == 200
    assert r.json()["iteration"] == 1 and r.json()["plan"]["requirements"]
