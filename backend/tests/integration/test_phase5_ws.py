"""Phase 5 exit gate: every agent step is visible live over /ws/tasks/{id}."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app
from tests.conftest import register_and_login
from tests.integration.test_phase4_loop import (
    HAPPY_LLM,
    failing_update_report,
    passing_report_for_demo,
    run,
)

API = "/api/v1"


def token(headers) -> str:
    return headers["Authorization"].split(" ", 1)[1]


def collect(client, tid, tok) -> list[dict]:
    with client.websocket_connect(f"/ws/tasks/{tid}?token={tok}") as ws:
        out = []
        while True:
            try:
                out.append(ws.receive_json())
            except WebSocketDisconnect:
                return out


@pytest.fixture
def finished(client):
    h, tid, _ = run(client, [failing_update_report(), passing_report_for_demo()], HAPPY_LLM)
    return h, tid


def test_full_loop_is_streamed_with_every_agent_step(client, finished):
    h, tid = finished
    events = collect(client, tid, token(h))
    names = [e["event"] for e in events]

    assert names[0] == "task_started" and names[-1] == "task_completed"
    started = [e["agent"] for e in events if e["event"] == "agent_started"]
    completed = [e["agent"] for e in events if e["event"] == "agent_completed"]
    # Planner and Builder once, then Verifier/Reviewer on iteration 1, Repair, and again on 2
    assert started[:2] == ["Planner", "Builder"]
    assert {"Verifier", "Reviewer", "Repair"} <= set(started)
    assert sorted(started) == sorted(completed)
    for needed in (
        "sandbox_started",
        "tests_completed",
        "iteration_completed",
        "retry_scheduled",
    ):
        assert needed in names
    assert names.count("tests_completed") == 2
    assert names.count("iteration_completed") == 2
    # the failing iteration reports its failure, the repaired one its success
    done = [e for e in events if e["event"] == "iteration_completed"]
    assert (done[0]["status"], done[0]["tests_failed"]) == ("failed", 1)
    assert (done[1]["status"], done[1]["tests_failed"]) == ("passed", 0)
    assert all(e["task_id"] == tid for e in events)
    assert len({e["id"] for e in events}) == len(events)


def test_a_late_subscriber_gets_the_same_history(client, finished):
    h, tid = finished
    assert collect(client, tid, token(h)) == collect(client, tid, token(h))


def test_events_are_in_chronological_order(client, finished):
    h, tid = finished
    events = collect(client, tid, token(h))
    # the terminal event is deliberately placed after its run's verdict (see event_stream)
    stamps = [e["timestamp"] for e in events if e["event"] != "task_completed"]
    assert stamps == sorted(stamps)
    assert events[-1]["event"] == "task_completed"


def test_missing_or_bad_token_is_refused(client, finished):
    _, tid = finished
    for url in (f"/ws/tasks/{tid}", f"/ws/tasks/{tid}?token=garbage"):
        with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect(url):
            pass
        assert exc.value.code == 4401


def test_foreign_and_unknown_tasks_look_the_same(client, finished):
    _, tid = finished
    other = token(register_and_login(client, "peek@x.com"))
    for target in (tid, "00000000-0000-0000-0000-000000000000"):
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            client.websocket_connect(f"/ws/tasks/{target}?token={other}"),
        ):
            pass
        assert exc.value.code == 4404


def test_logout_all_invalidates_the_socket_token(client, finished):
    h, tid = finished
    assert client.post(f"{API}/auth/logout-all", headers=h).status_code == 204
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(f"/ws/tasks/{tid}?token={token(h)}"),
    ):
        pass
    assert exc.value.code == 4401


def test_connection_limit_per_user(client, finished, monkeypatch):
    h, tid = finished
    monkeypatch.setattr(settings, "ws_max_connections_per_user", 0)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(f"/ws/tasks/{tid}?token={token(h)}"),
    ):
        pass
    assert exc.value.code == 4429


def test_running_task_stays_open_until_it_finishes(client, monkeypatch):
    """A PENDING task has no terminal state: the socket must stay open and deliver new events."""
    from tests.integration.test_phase5_analytics import new_task_for

    monkeypatch.setattr(settings, "ws_poll_seconds", 0.05)
    h = register_and_login(client, "live@x.com")
    _, tid = new_task_for(client, h)
    with client.websocket_connect(f"/ws/tasks/{tid}?token={token(h)}") as ws:
        # cancel while connected -> the cancelled event arrives, then the server closes
        assert client.post(f"{API}/tasks/{tid}/cancel", headers=h).status_code == 200
        event = ws.receive_json()
        assert event["event"] == "task_cancelled"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert app  # the app import keeps overrides alive for the fixture teardown
