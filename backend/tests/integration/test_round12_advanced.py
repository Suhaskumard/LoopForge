"""Round 12: failure explainer, auto pipelines, smart model routing."""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.database.models import AgentRun, CodeComment, Iteration, Notification, Pipeline, Task
from app.schemas.advanced import ExplainOutput, ModelStat
from app.services import pipeline_service, routing_service
from app.services.llm_client import LLMError
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import (
    DEFECTIVE,
    HAPPY_LLM,
    PLAN,
    failing_update_report,
    new_task,
    passing_report_for_demo,
    repair_output,
    run,
)

API = "/api/v1"


def escalated(client, email="why@x.com"):
    h, tid, _ = run(
        client, [failing_update_report()], [PLAN, DEFECTIVE, repair_output(), repair_output()], email=email
    )
    assert client.get(f"{API}/tasks/{tid}", headers=h).json()["status"] == "ESCALATED"
    return h, tid


def completed(client, email):
    h, tid, _ = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM, email=email)
    assert client.get(f"{API}/tasks/{tid}", headers=h).json()["status"] == "COMPLETED"
    return h, tid


# ---- 1. failure explainer ------------------------------------------------------------------------


def test_the_explainer_writes_an_ai_explanation_from_the_evidence(client):
    h, tid = escalated(client)
    client.llm.queue(
        ExplainOutput(
            summary="The update endpoint returns the wrong employee every time.",
            root_causes=["employee_id + 1 is used as the lookup key"],
            suggested_fix="Look the employee up by the id from the path, unchanged.",
            retry_note="In app/routes.py use employee_id as-is in the update handler.",
            confidence="high",
        )
    )
    r = client.post(f"{API}/tasks/{tid}/explanation", headers=h)
    assert r.status_code == 200, r.text
    exp = r.json()
    assert exp["source"] == "ai" and exp["confidence"] == "high"
    assert exp["evidence"]  # the facts the model was given are returned too
    prompt = client.llm.calls[-1]
    assert prompt.response_model == "ExplainOutput" and "Evidence:" in prompt.user
    assert client.get(f"{API}/tasks/{tid}/explanation", headers=h).json()["summary"] == exp["summary"]
    with client.factory() as db:
        assert db.scalars(select(AgentRun).where(AgentRun.agent_name == "Explainer")).first()


def test_without_a_model_answer_it_explains_from_the_evidence(client):
    h, tid = escalated(client, "evidence@x.com")
    client.llm.queue(LLMError("provider down"))
    exp = client.post(f"{API}/tasks/{tid}/explanation", headers=h).json()
    assert exp["source"] == "evidence"
    assert exp["summary"] and exp["root_causes"] and exp["retry_note"]


def test_retry_with_the_fix_hands_the_note_to_repair_and_runs_again(client):
    h, tid = escalated(client, "apply@x.com")
    client.llm.queue(LLMError("no model"))
    client.post(f"{API}/tasks/{tid}/explanation", headers=h)
    client.llm.queue(PLAN, DEFECTIVE, repair_output(), repair_output())
    r = client.post(f"{API}/tasks/{tid}/explanation/apply", headers=h)
    assert r.status_code == 202, r.text
    with client.factory() as db:
        notes = db.scalars(select(CodeComment).where(CodeComment.task_id == uuid.UUID(tid))).all()
        assert len(notes) == 1 and notes[0].body.startswith("Suggested fix from the failure analysis")
        assert not notes[0].resolved


def test_only_failed_tasks_can_be_explained_and_only_in_the_org(client):
    h, tid = new_task(client, "pending-x@x.com")
    assert client.post(f"{API}/tasks/{tid}/explanation", headers=h).status_code == 409
    assert client.post(f"{API}/tasks/{tid}/explanation/apply", headers=h).status_code == 409
    other = register_and_login(client, "nosy-x@x.com")
    assert client.get(f"{API}/tasks/{tid}/explanation", headers=other).status_code in (403, 404)


# ---- 2. pipelines --------------------------------------------------------------------------------


def _pipeline(client, h, steps=2):
    pid = client.post(f"{API}/projects", json={"name": "pipe"}, headers=h).json()["id"]
    body = {"project_id": pid, "name": "API then client",
            "steps": [{"requirement": f"Step {i + 1}: build the next part"} for i in range(steps)]}  # fmt: skip
    r = client.post(f"{API}/pipelines", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_an_accepted_step_starts_the_next_one_from_its_code(client):
    h, done_tid = completed(client, "pipe@x.com")
    pl = _pipeline(client, h)
    started: list[uuid.UUID] = []
    with client.factory() as db:
        p = db.get(Pipeline, uuid.UUID(pl["id"]))
        # step 1 "ran" as the completed task above
        p.steps[0].task_id, p.steps[0].status, p.status = uuid.UUID(done_tid), "running", "running"
        db.commit()
        task = db.get(Task, uuid.UUID(done_tid))
        pipeline_service.advance(db, task, started.append)
        pipeline_service.advance(db, task, started.append)  # a second hook call does nothing
        db.refresh(p)
        assert [s.status for s in p.steps] == ["accepted", "running"]
        nxt = db.get(Task, p.steps[1].task_id)
        assert started == [nxt.id] and nxt.status == "PLANNING"
        assert nxt.source_type == "task" and nxt.source_ref == done_tid and nxt.source_hash

        nxt.status = "COMPLETED"
        db.commit()
        pipeline_service.advance(db, nxt, started.append)
        db.refresh(p)
        assert p.status == "completed"
        assert db.scalars(select(Notification).where(Notification.kind == "pipeline.completed")).first()

    out = client.get(f"{API}/pipelines/{pl['id']}", headers=h).json()
    assert out["status"] == "completed" and [s["task_status"] for s in out["steps"]] == ["COMPLETED", "COMPLETED"]
    assert [p["id"] for p in client.get(f"{API}/pipelines", headers=h).json()] == [pl["id"]]


def test_a_failed_step_pauses_the_pipeline_and_resume_retries_it(client):
    h, bad_tid = escalated(client, "pause@x.com")
    pl = _pipeline(client, h)
    with client.factory() as db:
        p = db.get(Pipeline, uuid.UUID(pl["id"]))
        p.steps[0].task_id, p.steps[0].status, p.status = uuid.UUID(bad_tid), "running", "running"
        db.commit()
        pipeline_service.advance(db, db.get(Task, uuid.UUID(bad_tid)), lambda _id: None)
        db.refresh(p)
        assert p.status == "paused" and p.steps[0].status == "failed"
        assert db.scalars(select(Notification).where(Notification.kind == "pipeline.paused")).first()
    client.llm.queue(PLAN, DEFECTIVE, repair_output(), repair_output())
    r = client.post(f"{API}/pipelines/{pl['id']}/resume", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["steps"][0]["status"] == "running"
    assert client.post(f"{API}/pipelines/{pl['id']}/start", headers=h).status_code == 409  # not a draft


def test_pipelines_are_validated_and_private_to_the_org(client):
    h = register_and_login(client, "pv@x.com")
    pid = client.post(f"{API}/projects", json={"name": "p"}, headers=h).json()["id"]
    one = {"project_id": pid, "name": "x", "steps": [{"requirement": "only one step here"}]}
    assert client.post(f"{API}/pipelines", json=one, headers=h).status_code == 422
    pl = _pipeline(client, h)
    other = register_and_login(client, "pv-other@x.com")
    assert client.get(f"{API}/pipelines/{pl['id']}", headers=other).status_code == 404
    assert client.get(f"{API}/pipelines", headers=other).json() == []
    assert client.delete(f"{API}/projects/{pid}", headers=h).status_code == 204


# ---- 3. model routing ----------------------------------------------------------------------------


def _org(client, h):
    return client.get(f"{API}/orgs", headers=h).json()[0]["id"]


def test_org_routing_is_used_unless_the_task_overrides_it(client):
    from app.api.dependencies import get_sandbox
    from app.execution.fake_sandbox import ScriptedSandbox
    from app.main import app

    h, tid = new_task(client, "route@x.com")
    oid = _org(client, h)
    r = client.put(f"{API}/orgs/{oid}/routing", json={"routing": {"Planner": "cheap-model", "Builder": ""}}, headers=h)
    assert r.status_code == 200 and r.json()["routing"] == {"Planner": "cheap-model"}
    with client.factory() as db:
        db.get(Task, uuid.UUID(tid)).model_overrides = {"Builder": "task-model"}
        db.commit()
    app.dependency_overrides[get_sandbox] = lambda: ScriptedSandbox([failing_update_report(), passing_report_for_demo()])
    client.llm.queue(*HAPPY_LLM)
    client.post(f"{API}/tasks/{tid}/start", headers=h)
    with client.factory() as db:
        models = {r.agent_name: r.model for r in db.scalars(select(AgentRun))}
    assert models["Planner"] == "cheap-model" and models["Builder"] == "task-model"
    bad = client.put(f"{API}/orgs/{oid}/routing", json={"routing": {"Wizard": "x"}}, headers=h)
    assert bad.status_code == 422
    assert client.put(f"{API}/orgs/{oid}/routing", json={"routing": {"Planner": "bad model!"}}, headers=h).status_code == 422


def test_recommendation_picks_the_cheapest_model_that_is_nearly_as_good():
    def stat(model, rate, cost, tasks=8):
        return ModelStat(agent="Repair", model=model, runs=tasks * 2, tasks=tasks, accepted=round(rate * tasks),
                         accept_rate=rate, tokens_per_run=100, cost_per_run=cost)  # fmt: skip

    recs = {r.agent: r for r in routing_service.recommend([
        stat("big", 0.9, 0.05), stat("medium", 0.85, 0.01), stat("tiny", 0.5, 0.001), stat("new", 1.0, 0.0001, tasks=2),
    ])}  # fmt: skip
    assert recs["Repair"].model == "medium"  # within 10 points of the best, and cheaper than big
    assert recs["Planner"].model is None and "Not enough evidence" in recs["Planner"].reason


def test_routing_stats_come_from_the_orgs_own_runs(client):
    h, _ = completed(client, "stats@x.com")
    oid = _org(client, h)
    with client.factory() as db:
        for run_ in db.scalars(select(AgentRun)):
            run_.model = "m1"
            run_.started_at = datetime.now()
        db.commit()
    out = client.get(f"{API}/orgs/{oid}/routing", headers=h).json()
    repair = next(s for s in out["stats"] if s["agent"] == "Repair")
    assert repair["model"] == "m1" and repair["tasks"] == 1 and repair["accept_rate"] == 1.0
    other = register_and_login(client, "stats-other@x.com")
    assert client.get(f"{API}/orgs/{oid}/routing", headers=other).status_code == 404
    with client.factory() as db:
        assert db.scalars(select(Iteration)).first() is not None
