"""Real-container checks of the §13.1 controls and the Phase 3 exit gate.

Needs a running Docker daemon and the image:  docker build -t loopforge-sandbox backend/sandbox
Run with:  pytest -m docker
"""

import subprocess
import time

import pytest

from app.config import settings
from app.evaluation.test_runner import run_tests
from app.execution.sandbox import DockerSandbox, docker_available


def _ready() -> bool:
    if not docker_available():
        return False
    r = subprocess.run(["docker", "image", "inspect", settings.sandbox_image], capture_output=True)
    return r.returncode == 0


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _ready(), reason="Docker daemon or sandbox image unavailable"),
]


def _project(tmp_path, tests: dict[str, str]):
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True)
    for name, body in tests.items():
        (src / "tests" / name).write_text(body, encoding="utf-8")
    return src, tmp_path / "out"


def _leftovers() -> str:
    r = subprocess.run(
        ["docker", "ps", "-a", "-q", "--filter", "label=loopforge.sandbox=1"],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def test_passing_and_broken_code(tmp_path):
    src, out = _project(
        tmp_path,
        {
            "test_ok.py": "def test_ok():\n    assert 1 + 1 == 2\n",
            "test_bad.py": "def test_bad():\n    assert {}['k']\n",
        },
    )
    summary, _ = run_tests(DockerSandbox(), src, out, 60)
    assert summary.passed == 1 and summary.failed == 1
    assert "KeyError" in summary.failures[0].traceback  # captured stack trace
    assert _leftovers() == ""


def test_runaway_process_is_killed_and_container_removed(tmp_path):
    src, out = _project(
        tmp_path, {"test_loop.py": "def test_loop():\n    while True:\n        pass\n"}
    )
    started = time.monotonic()
    summary, _ = run_tests(DockerSandbox(), src, out, 8)
    assert summary.timed_out and not summary.ok
    assert time.monotonic() - started < 40
    assert _leftovers() == ""


def test_isolation_controls_hold_inside_the_container(tmp_path):
    src, out = _project(
        tmp_path,
        {
            "test_iso.py": (
                "import os, socket, pytest\n"
                "def test_non_root():\n    assert os.getuid() != 0\n"
                "def test_rootfs_read_only():\n"
                "    with pytest.raises(OSError):\n        open('/etc/pwned', 'w')\n"
                "def test_source_mount_read_only():\n"
                "    with pytest.raises(OSError):\n        open('/workspace/x', 'w')\n"
                "def test_no_network():\n"
                "    with pytest.raises(OSError):\n"
                "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
                "def test_no_docker_socket():\n"
                "    assert not os.path.exists('/var/run/docker.sock')\n"
                "def test_cannot_install_packages():\n"
                "    import importlib.util\n    assert importlib.util.find_spec('pip') is None\n"
            )
        },
    )
    summary, _ = run_tests(DockerSandbox(), src, out, 60)
    assert summary.ok and summary.passed == 6, summary.failures
