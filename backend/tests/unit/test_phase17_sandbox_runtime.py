# ruff: noqa: E501
"""Phase 17: configurable sandbox runtime (gVisor/Kata) - argument building and the fail-closed check.

No hardened runtime is installed on the development machine, so `docker info` is mocked here. What is
proved: the flag is added only when asked for, a missing runtime refuses to run (never falls back to
runc), and a plain-runc production deployment can be forbidden. What is NOT proved: isolation under
gVisor itself, or its performance cost (to be measured on a host that has it; see docs/security_model.md).
"""

import json
import subprocess
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.execution import sandbox
from app.execution.sandbox import DockerSandbox, SandboxError, build_run_args


def info(runtimes: dict, code: int = 0):
    def fake(cmd, **kw):
        assert cmd[:2] == ["docker", "info"]
        return subprocess.CompletedProcess(
            cmd, code, stdout=json.dumps(runtimes).encode(), stderr=b""
        )

    return fake


def args(tmp_path: Path) -> list[str]:
    return build_run_args("n", tmp_path / "w", tmp_path / "o", ["python", "-m", "pytest"])


def test_runc_is_the_default_and_adds_no_runtime_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_runtime", "runc")
    assert "--runtime" not in args(tmp_path)


def test_a_hardened_runtime_is_passed_to_docker_and_all_other_controls_remain(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "sandbox_runtime", "runsc")
    a = args(tmp_path)
    assert a[a.index("--runtime") + 1] == "runsc"
    for control in ("--read-only", "--cap-drop", "--network", "--pids-limit", "--memory"):
        assert control in a
    assert a[a.index("--network") + 1] == "none"
    assert a.index("--runtime") < a.index("--network")  # a docker option, before the image


def test_installed_runtimes_parses_docker_info(monkeypatch):
    monkeypatch.setattr(sandbox.subprocess, "run", info({"runc": {}, "runsc": {"path": "/x"}}))
    assert sandbox.installed_runtimes() == {"runc", "runsc"}


@pytest.mark.parametrize("failure", [OSError("no docker"), subprocess.TimeoutExpired("docker", 15)])
def test_a_daemon_that_cannot_be_asked_reports_no_runtimes(monkeypatch, failure):
    def boom(*a, **k):
        raise failure

    monkeypatch.setattr(sandbox.subprocess, "run", boom)
    assert sandbox.installed_runtimes() == set()


def test_unparseable_or_failing_docker_info_reports_no_runtimes(monkeypatch):
    monkeypatch.setattr(
        sandbox.subprocess,
        "run",
        lambda c, **k: subprocess.CompletedProcess(c, 0, b"not json", b""),
    )
    assert sandbox.installed_runtimes() == set()
    monkeypatch.setattr(sandbox.subprocess, "run", info({"runc": {}}, code=1))
    assert sandbox.installed_runtimes() == set()


def test_missing_runtime_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_runtime", "runsc")
    monkeypatch.setattr(sandbox.subprocess, "run", info({"runc": {}, "nvidia": {}}))
    with pytest.raises(SandboxError, match="'runsc' is not installed.*refusing to fall back"):
        sandbox.check_runtime()


def test_present_runtime_passes_and_runc_never_asks_the_daemon(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_runtime", "kata")
    monkeypatch.setattr(sandbox.subprocess, "run", info({"kata": {}}))
    assert sandbox.check_runtime() == "kata"
    monkeypatch.setattr(settings, "sandbox_runtime", "runc")
    monkeypatch.setattr(
        sandbox.subprocess, "run", lambda *a, **k: pytest.fail("must not call docker")
    )
    assert sandbox.check_runtime() == "runc"


def test_a_run_with_a_missing_runtime_never_starts_a_container(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_runtime", "runsc")
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=b'{"runc": {}}', stderr=b"")

    monkeypatch.setattr(sandbox.subprocess, "run", fake)
    (tmp_path / "w").mkdir()
    with pytest.raises(SandboxError, match="not installed"):
        DockerSandbox().run(tmp_path / "w", tmp_path / "o", ["python", "-V"], timeout=5)
    assert all(c[:2] == ["docker", "info"] for c in calls)  # info only: no `docker run`


@pytest.mark.parametrize("bad", ["", "Runsc", "run sc", "runsc;rm", "-x", "a" * 40])
def test_runtime_names_are_validated(bad):
    with pytest.raises(ValueError, match="SANDBOX_RUNTIME"):
        Settings(sandbox_runtime=bad)


def test_production_can_forbid_plain_runc():
    base = dict(
        environment="production", jwt_secret="j" * 40, secrets_key="s" * 40, llm_provider="openai",
        sandbox_backend="docker", mail_backend="smtp",
    )  # fmt: skip
    with pytest.raises(ValueError, match="SANDBOX_REQUIRE_HARDENED_RUNTIME"):
        Settings(**base, sandbox_require_hardened_runtime=True)
    Settings(**base, sandbox_require_hardened_runtime=True, sandbox_runtime="runsc")
    Settings(**base)  # opt-in: plain runc stays allowed unless the guard is on
