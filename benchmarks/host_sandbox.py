"""HostSandbox: runs allowlisted commands as plain subprocesses on THIS machine.

!!! NOT A SANDBOX. It exists only so the benchmark harness can be validated end to end without
Docker, using the project's own trusted reference solutions (the `oracle` provider). It refuses to
be used with any real model (see run_benchmarks.py): model-generated code must go through the
Docker sandbox.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.execution.fake_sandbox import _tool_result  # noqa: E402
from app.execution.sandbox import CONTAINER_OUT, CONTAINER_WORKSPACE, ExecResult  # noqa: E402


class HostSandbox:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, workspace: Path, out_dir: Path, argv: list[str], timeout: int) -> ExecResult:
        self.calls.append(argv)
        tool = _tool_result(argv)  # ruff / bandit: canned clean output (not what is measured)
        if tool is not None:
            return tool
        out_dir.mkdir(parents=True, exist_ok=True)
        # Like the real sandbox (read-only source mount), the workspace itself is never written to:
        # run in a throw-away copy so .coverage / __pycache__ never pollute the iteration.
        with tempfile.TemporaryDirectory(prefix="lf_host_") as tmp:
            work = Path(tmp) / "workspace"
            shutil.copytree(workspace, work)
            mapped = [
                a.replace(CONTAINER_WORKSPACE, str(work)).replace(CONTAINER_OUT, str(out_dir))
                for a in argv
            ]
            if mapped[:3] == ["python", "-m", "pytest"]:
                mapped[0] = sys.executable
            started = time.perf_counter()
            try:
                proc = subprocess.run(
                    mapped, cwd=work, capture_output=True, text=True, timeout=timeout, check=False
                )
            except subprocess.TimeoutExpired:
                return ExecResult("", "timeout", 124, True, time.perf_counter() - started)
            return ExecResult(
                proc.stdout, proc.stderr, proc.returncode, False, time.perf_counter() - started
            )
