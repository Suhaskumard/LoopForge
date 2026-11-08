"""Sandbox boundary (spec §13.1 / Addendum §19.1). Generated code NEVER runs on the API host.

`DockerSandbox` drives the `docker` CLI (no SDK, and the Docker socket is never mounted into the
container). Every container gets: non-root user, read-only root FS, no network, dropped
capabilities, no-new-privileges, CPU/memory/PID limits, only the task workspace mounted, a wall
clock timeout enforced from outside, and unconditional removal afterwards.
Ordinary containers are not an absolute security boundary; see docs/security_model.md.
"""

import logging
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import settings
from app.execution.languages import image_for_argv
from app.utils.metrics import SANDBOX_DURATION, SANDBOX_RUNS

log = logging.getLogger("loopforge.sandbox")

SANDBOX_UID = 10001
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_OUT = "/out"
_TRUNCATED = "\n[output truncated]"
# `docker run` exit codes meaning docker itself failed (125) or the command could not be
# started inside the container (126 not executable, 127 not found).
DOCKER_FAILURE_CODES = {125, 126, 127}


class SandboxError(Exception):
    """Infrastructure failure (docker missing, daemon down). Not a test failure."""


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_seconds: float


class Sandbox(Protocol):
    def run(self, workspace: Path, out_dir: Path, argv: list[str], timeout: int) -> ExecResult:
        """Run `argv` with `workspace` mounted read-only and `out_dir` writable."""
        ...


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + _TRUNCATED


def build_run_args(name: str, workspace: Path, out_dir: Path, argv: list[str]) -> list[str]:
    """The exact `docker run` command line. Pure so the §13.1 controls can be unit-tested."""
    for p in (workspace, out_dir):
        if "," in str(p):  # would inject extra --mount options
            raise SandboxError(f"unsupported character in sandbox path: {p}")
    mem = f"{settings.sandbox_memory_mb}m"
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "--user", f"{SANDBOX_UID}:{SANDBOX_UID}",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",  # nosec B108 - path inside the container
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", mem,
        "--memory-swap", mem,
        "--cpus", str(settings.sandbox_cpus),
        "--pids-limit", str(settings.sandbox_pids_limit),
        "--ulimit", "nofile=256:256",
        "--label", "loopforge.sandbox=1",
        "--env", "HOME=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "COVERAGE_FILE=/tmp/.coverage",
        "--mount", f"type=bind,source={workspace},target={CONTAINER_WORKSPACE},readonly",
        "--mount", f"type=bind,source={out_dir},target={CONTAINER_OUT}",
        "--workdir", CONTAINER_WORKSPACE,
        image_for_argv(argv),
        *argv,
    ]  # fmt: skip


class DockerSandbox:
    def run(self, workspace: Path, out_dir: Path, argv: list[str], timeout: int) -> ExecResult:
        workspace, out_dir = workspace.resolve(), out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            out_dir.chmod(0o777)  # the unprivileged sandbox user must be able to write reports
        except OSError:  # Windows hosts: bind-mount permissions come from Docker Desktop
            pass
        name = f"loopforge-sbx-{uuid.uuid4().hex[:12]}"
        cmd = build_run_args(name, workspace, out_dir, argv)
        started = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout, stderr, code = exc.stdout or b"", exc.stderr or b"", 124
            self._kill(name)
        except FileNotFoundError:
            raise SandboxError("docker CLI not found") from None
        finally:
            self._remove(name)  # explicit cleanup, always
        if code in DOCKER_FAILURE_CODES and not timed_out:
            # The container never ran the command (daemon down, image missing, bad command). That
            # is an infrastructure failure, not a failing test: the loop must not "repair" code.
            detail = _text(stderr).strip()[:300] or f"exit {code}"
            SANDBOX_RUNS.inc(outcome="infrastructure_error")
            raise SandboxError(f"docker could not run the sandbox: {detail}")
        limit = settings.sandbox_max_output_bytes
        elapsed = time.perf_counter() - started
        SANDBOX_DURATION.observe(elapsed)
        SANDBOX_RUNS.inc(outcome="timeout" if timed_out else ("ok" if code == 0 else "nonzero"))
        return ExecResult(
            stdout=truncate(_text(stdout), limit),
            stderr=truncate(_text(stderr), limit),
            exit_code=code,
            timed_out=timed_out,
            duration_seconds=elapsed,
        )

    @staticmethod
    def _kill(name: str) -> None:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=30, check=False)

    @staticmethod
    def _remove(name: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):
            log.error("could not remove sandbox container %s", name)


def _text(data: bytes | str) -> str:
    return data if isinstance(data, str) else data.decode("utf-8", "replace")


def docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def get_sandbox_backend() -> Sandbox:
    if settings.sandbox_backend == "fake":
        from app.execution.fake_sandbox import FakeSandbox

        return FakeSandbox()
    return DockerSandbox()
