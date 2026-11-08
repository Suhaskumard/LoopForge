"""Phase 12: log correlation ids, metrics, alert rules, DB pool settings, worker metrics."""

import io
import json
import logging
import re
import threading
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from app.config import settings
from app.database.models import AgentRun, Iteration, Job, RunLease
from app.database.session import make_engine
from app.services import job_service, lease_service, ops_metrics
from app.services.llm_client import FakeLLMClient, _SlowFakeLLM, get_llm_client
from app.utils import metrics
from app.utils.logging import JsonFormatter, bind, request_id_var, task_id_var, thread_target
from app.utils.metrics import REGISTRY, Counter, Gauge, Histogram, Registry
from app.worker import run_once
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import (
    HAPPY_LLM,
    failing_update_report,
    passing_report_for_demo,
)
from tests.integration.test_phase7_scale import _task

API = "/api/v1"
DEPLOY = Path(__file__).resolve().parents[3] / "deploy" / "observability"


@contextmanager
def json_logs():
    """Capture root logging output through the production JSON formatter."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield lambda: [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


# ---- the metrics library --------------------------------------------------------------------


def test_exposition_format_for_each_metric_kind():
    reg = Registry()
    c = reg.counter("t_requests_total", "Requests.", ["route"])
    g = reg.gauge("t_depth", "Depth.")
    h = reg.histogram("t_seconds", "Latency.", ["route"], buckets=[0.1, 1.0])
    c.inc(route="/a")
    c.inc(2, route="/a")
    g.set(7)
    for v in (0.05, 0.5, 5.0):
        h.observe(v, route="/a")
    text = reg.render()
    assert "# HELP t_requests_total Requests.\n# TYPE t_requests_total counter\n" in text
    assert 't_requests_total{route="/a"} 3\n' in text
    assert "# TYPE t_depth gauge\nt_depth 7\n" in text
    # histogram buckets are cumulative and end with +Inf == count
    assert 't_seconds_bucket{route="/a",le="0.1"} 1\n' in text
    assert 't_seconds_bucket{route="/a",le="1"} 2\n' in text
    assert 't_seconds_bucket{route="/a",le="+Inf"} 3\n' in text
    assert 't_seconds_count{route="/a"} 3\n' in text and 't_seconds_sum{route="/a"} 5.55\n' in text
    assert h.count(route="/a") == 3 and c.value(route="/a") == 3 and g.value() == 7


def test_label_values_are_escaped():
    reg = Registry()
    c = reg.counter("t_x_total", "x", ["v"])
    c.inc(v='quo"te\\back\nline')
    assert 't_x_total{v="quo\\"te\\\\back\\nline"} 1' in reg.render()


def test_misuse_is_rejected():
    reg = Registry()
    c = reg.counter("t_a_total", "a", ["x"])
    with pytest.raises(ValueError, match="takes labels"):
        c.inc(y="1")
    with pytest.raises(ValueError, match="takes labels"):
        c.inc()
    with pytest.raises(ValueError, match="only goes up"):
        c.inc(-1, x="1")
    with pytest.raises(ValueError, match="already registered"):
        reg.counter("t_a_total", "again")
    assert isinstance(reg.gauge("t_g", "g"), Gauge) and isinstance(
        reg.histogram("t_h", "h"), Histogram
    )
    assert isinstance(Counter("c", "c"), Counter)


def test_registry_names_include_histogram_series():
    reg = Registry()
    reg.histogram("t_h", "h")
    reg.counter("t_c_total", "c")
    assert reg.names() == {"t_h", "t_h_bucket", "t_h_sum", "t_h_count", "t_c_total"}


# ---- /metrics ---------------------------------------------------------------------------------


def test_metrics_are_404_unless_enabled(client):
    assert client.get("/metrics").status_code == 404


def test_metrics_endpoint_serves_series_and_hides_ids(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    before_4xx = metrics.HTTP_REQUESTS.value(
        method="GET", route="/api/v1/tasks", status_class="4xx"
    )
    h = register_and_login(client, "m@x.com")
    task = _task(client, h)
    for _ in range(3):
        client.get(f"{API}/tasks/{task['id']}", headers=h)
    client.get(f"{API}/tasks/{uuid.uuid4()}", headers=h)  # a 404
    client.get(f"{API}/tasks")  # a 401
    r = client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith(
        "text/plain; version=0.0.4"
    )
    body = r.text
    # the route TEMPLATE is the label: one series for every task id, never the raw path
    assert 'route="/api/v1/tasks/{task_id}"' in body
    assert task["id"] not in body
    assert (
        metrics.HTTP_REQUESTS.value(method="GET", route="/api/v1/tasks", status_class="4xx")
        == before_4xx + 1
    )  # exactly the one 401 made above (a delta: the registry lives per process)
    assert "loopforge_http_request_duration_seconds_bucket" in body
    assert 'loopforge_tasks{status="PENDING"} 1' in body
    assert 'loopforge_build_info{version="12"} 1' in body
    assert "loopforge_jobs_queued 0" in body


def test_metrics_token_is_enforced(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", "scrape-secret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 200
    )
    monkeypatch.setattr(settings, "metrics_enabled", False)
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 404
    )


def test_database_gauges_describe_queue_leases_and_tokens(client):
    h = register_and_login(client, "g@x.com")
    task_id = uuid.UUID(_task(client, h)["id"])
    now = datetime(2026, 11, 8, 12, 0, 0)
    with client.factory() as db:
        db.add(
            Job(
                task_id=task_id,
                kind="start",
                status="queued",
                created_at=now - timedelta(minutes=10),
            )
        )
        db.add(Job(task_id=task_id, kind="resume", status="running"))
        db.add(
            RunLease(
                task_id=task_id, owner="w", expires_at=now + timedelta(seconds=30), acquired_at=now
            )
        )
        other = uuid.UUID(_task(client, h)["id"])
        db.add(
            RunLease(
                task_id=other, owner="dead", expires_at=now - timedelta(seconds=60), acquired_at=now
            )
        )
        it = Iteration(task_id=task_id, iteration_number=1)
        db.add(it)
        db.flush()
        db.add(AgentRun(iteration_id=it.id, agent_name="Builder", tokens_used=321, started_at=now))
        db.commit()
        ops_metrics.refresh_db_gauges(db, now)
    assert metrics.JOBS_QUEUED.value() == 1 and metrics.JOBS_RUNNING.value() == 1
    assert metrics.JOBS_OLDEST_QUEUED_AGE.value() == 600
    assert metrics.ACTIVE_LEASES.value() == 1 and metrics.EXPIRED_LEASES.value() == 1
    assert metrics.TOKENS_MONTH.value() == 321
    assert metrics.TASKS.value(status="PENDING") == 2


def test_gauges_reset_when_the_queue_is_empty(client):
    with client.factory() as db:
        ops_metrics.refresh_db_gauges(db)
    assert metrics.JOBS_OLDEST_QUEUED_AGE.value() == 0 and metrics.JOBS_QUEUED.value() == 0


def test_agent_calls_and_tokens_are_counted(client):
    before_ok = metrics.LLM_CALLS.value(agent="Planner", outcome="success")
    before_tokens = metrics.LLM_TOKENS.value(agent="Planner")
    client.llm.queue(*HAPPY_LLM)
    h = register_and_login(client, "calls@x.com")
    t = _task(client, h)
    from app.api.dependencies import get_sandbox
    from app.execution.fake_sandbox import ScriptedSandbox
    from app.main import app

    app.dependency_overrides[get_sandbox] = lambda: ScriptedSandbox(
        [failing_update_report(), passing_report_for_demo()]
    )
    assert client.post(f"{API}/tasks/{t['id']}/start", headers=h).status_code == 202
    assert metrics.LLM_CALLS.value(agent="Planner", outcome="success") == before_ok + 1
    assert metrics.LLM_TOKENS.value(agent="Planner") > before_tokens
    assert metrics.LLM_CALLS.value(agent="Repair", outcome="success") >= 1


# ---- leases: takeover is counted and logged ---------------------------------------------------


def test_lease_takeover_is_counted_and_logged_but_renewal_is_not(client):
    h = register_and_login(client, "lease@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    base = metrics.LEASE_TAKEOVERS.value()
    with json_logs() as logs, client.factory() as db:
        assert lease_service.acquire(db, tid, owner="A", ttl=0.05)  # fresh insert: not a takeover
        assert lease_service.acquire(db, tid, owner="A", ttl=0.05)  # same owner: not a takeover
        assert metrics.LEASE_TAKEOVERS.value() == base
        threading.Event().wait(0.15)
        assert lease_service.acquire(db, tid, owner="B")  # A stopped renewing: takeover
    assert metrics.LEASE_TAKEOVERS.value() == base + 1
    line = next(x for x in logs() if "lease takeover" in x["msg"])
    assert str(tid) in line["msg"] and "from A to B" in line["msg"] and line["level"] == "WARNING"


# ---- correlation ids ---------------------------------------------------------------------------


def test_the_access_log_line_carries_the_requests_own_id(client):
    with json_logs() as logs:
        r = client.get("/health", headers={"X-Request-ID": "req-abc-123"})
    assert r.headers["X-Request-ID"] == "req-abc-123"
    access = [x for x in logs() if x["logger"] == "loopforge.http" and "/health" in x["msg"]]
    assert access and access[0]["request_id"] == "req-abc-123"  # was "-" before Phase 12


def test_request_id_flows_from_the_api_through_the_job_to_the_worker(client, monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "queue")
    client.llm.queue(*HAPPY_LLM)
    h = register_and_login(client, "trace@x.com")
    t = _task(client, h)
    r = client.post(f"{API}/tasks/{t['id']}/start", headers={**h, "X-Request-ID": "trace-77"})
    assert r.status_code == 202
    with client.factory() as db:
        assert db.query(Job).one().request_id == "trace-77"
    from app.execution.fake_sandbox import ScriptedSandbox

    sandbox = ScriptedSandbox([failing_update_report(), passing_report_for_demo()])
    with json_logs() as logs:
        assert run_once(client.factory, client.llm, sandbox, worker="w1")
    worker_lines = [x for x in logs() if x["request_id"] == "trace-77"]
    assert {"loopforge.worker"} <= {x["logger"] for x in worker_lines}
    claimed = next(x for x in worker_lines if "claimed by w1" in x["msg"])
    assert claimed["task_id"] == t["id"] and claimed["job_id"]
    assert all(
        x["task_id"] == t["id"] for x in worker_lines
    )  # every line of this job is attributable
    assert request_id_var.get() == "-" and task_id_var.get() == "-"  # nothing leaks after the job


def test_a_job_without_a_request_still_gets_a_traceable_id(client):
    h = register_and_login(client, "norid@x.com")
    tid = uuid.UUID(_task(client, h)["id"])
    with client.factory() as db:
        job_service.enqueue(db, tid, "resume")  # e.g. created by `recover`, no HTTP request
    with json_logs() as logs:
        run_once(client.factory, FakeLLMClient(), None, worker="w2")  # type: ignore[arg-type]
    assert any(x["request_id"].startswith("job-") for x in logs())


def test_ids_cross_threads_only_through_thread_target():
    seen: dict[str, str] = {}

    def probe(key: str) -> None:
        seen[key] = task_id_var.get()

    with bind(task_id="T-1"):
        plain = threading.Thread(target=probe, args=("plain",))
        wrapped = threading.Thread(target=thread_target(probe), args=("wrapped",))
        for t in (plain, wrapped):
            t.start()
            t.join()
    assert seen == {"plain": "-", "wrapped": "T-1"}
    assert task_id_var.get() == "-"


def test_bind_restores_previous_values_even_after_errors():
    with bind(request_id="outer"):
        with pytest.raises(RuntimeError):
            with bind(request_id="inner", task_id="t", job_id="j"):
                raise RuntimeError("boom")
        assert request_id_var.get() == "outer" and task_id_var.get() == "-"
    assert request_id_var.get() == "-"


def test_formatter_omits_unset_optional_ids():
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "hello", (), None)
    assert set(json.loads(JsonFormatter().format(rec))) == {
        "ts",
        "level",
        "logger",
        "msg",
        "request_id",
    }
    with bind(task_id="T", job_id="J"):
        out = json.loads(JsonFormatter().format(rec))
    assert out["task_id"] == "T" and out["job_id"] == "J"


# ---- alert rules and dashboard stay consistent with the registry -------------------------------


def _metric_names_in(text: str) -> set[str]:
    return set(re.findall(r"\bloopforge_[a-z0-9_]+", text))


def test_every_metric_in_alerts_dashboard_and_autoscaling_exists():
    known = REGISTRY.names()
    for name in ("alerts.yml", "grafana-dashboard.json", "keda-worker-scaledobject.yaml"):
        used = _metric_names_in((DEPLOY / name).read_text(encoding="utf-8"))
        assert used, name
        assert used - known == set(), f"{name} references metrics that do not exist: {used - known}"


def test_alert_rules_are_well_formed():
    doc = yaml.safe_load((DEPLOY / "alerts.yml").read_text(encoding="utf-8"))
    rules = [r for g in doc["groups"] for r in g["rules"]]
    assert len(rules) >= 8
    names = [r["alert"] for r in rules]
    assert len(set(names)) == len(names)
    for r in rules:
        assert r["expr"].strip() and r["labels"]["severity"] in {"page", "warn", "info"}
        assert r["annotations"]["summary"] and r["annotations"]["runbook"].startswith(
            "docs/operations.md#"
        )


def test_alert_runbook_anchors_exist_in_the_operations_guide():
    guide = (DEPLOY.parents[1] / "docs" / "operations.md").read_text(encoding="utf-8")
    anchors = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
        for h in re.findall(r"^#+ (.+)$", guide, re.M)
    }
    doc = yaml.safe_load((DEPLOY / "alerts.yml").read_text(encoding="utf-8"))
    for g in doc["groups"]:
        for r in g["rules"]:
            assert r["annotations"]["runbook"].split("#", 1)[1] in anchors, r["alert"]


def test_dashboard_is_valid_json_with_unique_panels():
    dash = json.loads((DEPLOY / "grafana-dashboard.json").read_text(encoding="utf-8"))
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids)) >= 10 and all(p["targets"] for p in dash["panels"])
    assert (
        yaml.safe_load((DEPLOY / "keda-worker-scaledobject.yaml").read_text(encoding="utf-8"))[
            "kind"
        ]
        == "ScaledObject"
    )


# ---- DB pool, fake LLM delay, worker metrics server ----------------------------------------------


def test_engines_ping_connections_before_use(tmp_path):
    assert make_engine(f"sqlite:///{tmp_path / 'a.db'}").pool._pre_ping is True
    pg = make_engine("postgresql+psycopg://u:p@localhost:5432/db")  # lazy: nothing connects
    assert pg.pool._pre_ping is True
    assert (
        pg.pool.size() == settings.db_pool_size
        and pg.pool._max_overflow == settings.db_max_overflow
    )
    assert pg.pool._recycle == settings.db_pool_recycle_seconds
    pg.dispose()


def test_pre_ping_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_pool_pre_ping", False)
    assert make_engine(f"sqlite:///{tmp_path / 'b.db'}").pool._pre_ping is False


def test_fake_llm_delay_is_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "fake")
    assert type(get_llm_client()) is FakeLLMClient
    monkeypatch.setattr(settings, "fake_llm_delay_seconds", 0.01)
    slow = get_llm_client()
    assert isinstance(slow, _SlowFakeLLM) and slow.delay == 0.01


def test_worker_metrics_server_serves_this_process_registry():
    from app.utils import metrics_server

    metrics.JOBS_FINISHED.inc(status="done")
    server = metrics_server.start(0, host="127.0.0.1")
    try:
        port = server.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()  # noqa: S310
        assert "loopforge_jobs_finished_total" in body
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/other", timeout=5)  # noqa: S310
        assert err.value.code == 404
    finally:
        server.shutdown()
