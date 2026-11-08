"""Phase 11: the `loopforge` CLI, against a mock API."""

import httpx
import pytest

from app import cli


def _api(statuses, calls):
    states = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("Authorization")))
        path = request.url.path
        if path.endswith("/projects"):
            return httpx.Response(201, json={"id": "p1"})
        if path.endswith("/tasks"):
            return httpx.Response(201, json={"id": "t1", "status": "PENDING"})
        if path.endswith("/start"):
            return httpx.Response(202, json={"id": "t1", "status": "PENDING"})
        if path.endswith("/publish"):
            return httpx.Response(201, json={"id": "r1", "status": "requested"})
        if path.endswith("/boom"):
            return httpx.Response(403, json={"error": {"message": "Requires the developer role"}})
        return httpx.Response(200, json={"id": "t1", "status": next(states)})

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("LOOPFORGE_TOKEN", "lfk_" + "x" * 40)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)


def test_run_without_wait_prints_and_exits_zero(capsys):
    calls = []
    code = cli.main(
        ["run", "--repo", "https://github.com/o/r.git", "--requirement", "add x"],
        _api([], calls),
    )
    assert code == 0 and "task t1" in capsys.readouterr().out
    assert [c[1] for c in calls] == [
        "/api/v1/projects",
        "/api/v1/tasks",
        "/api/v1/tasks/t1/start",
    ]
    assert all(c[2] == "Bearer lfk_" + "x" * 40 for c in calls)


@pytest.mark.parametrize(("final", "code"), [("COMPLETED", 0), ("ESCALATED", 1), ("FAILED", 1)])
def test_run_wait_exit_code_follows_the_verdict(final, code, capsys):
    out = cli.main(
        ["run", "--repo", "https://h/o/r", "--requirement", "r", "--wait"],
        _api(["TESTING", final], []),
    )
    assert out == code and final in capsys.readouterr().out


def test_wait_times_out(capsys):
    out = cli.main(
        ["run", "--repo", "https://h/o/r", "--requirement", "r", "--wait", "--timeout", "-1"],
        _api(["TESTING"], []),
    )
    assert out == 2 and "timed out" in capsys.readouterr().err


def test_publish_command(capsys):
    assert cli.main(["publish", "t1", "--repo", "o/r"], _api([], [])) == 0
    assert "waiting for an approver" in capsys.readouterr().out


def test_missing_token_and_api_errors(monkeypatch, capsys):
    monkeypatch.delenv("LOOPFORGE_TOKEN")
    assert cli.main(["publish", "t1", "--repo", "o/r"], _api([], [])) == 2
    assert "LOOPFORGE_TOKEN" in capsys.readouterr().err
    monkeypatch.setenv("LOOPFORGE_TOKEN", "lfk_" + "x" * 40)
    api = cli.Api("http://x", "t", _api([], []))
    with pytest.raises(cli.CliError, match="403: Requires the developer role"):
        api.call("GET", "/boom")


def test_unreachable_server_is_a_clean_error(capsys):
    def down(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(down))
    assert cli.main(["publish", "t1", "--repo", "o/r"], client) == 2
    assert "cannot reach the server" in capsys.readouterr().err
