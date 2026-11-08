# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: the complete feedback loop with the REAL Docker sandbox (no scripted test results).

The model is still the built-in fake (a plan, a Builder output with an injected defect, a repair, a review), but
the tests are executed for real: pytest runs inside a locked-down container, fails on the injected defect,
and passes after the repair. Needs a running Docker daemon and the image:
    docker build -t loopforge-sandbox backend/sandbox
Run with: pytest -m docker
"""

import subprocess

import pytest

from app.api.dependencies import get_sandbox
from app.config import settings
from app.execution.sandbox import DockerSandbox, docker_available
from app.main import app
from tests.integration.test_phase4_loop import HAPPY_LLM, iterations, new_task

pytestmark = pytest.mark.docker

API = "/api/v1"


@pytest.fixture(autouse=True)
def _need_docker():
    if not docker_available():
        pytest.skip("no Docker daemon")
    image = subprocess.run(
        ["docker", "image", "inspect", settings.sandbox_image], capture_output=True
    )
    if image.returncode != 0:
        pytest.skip(
            f"sandbox image missing: docker build -t {settings.sandbox_image} backend/sandbox"
        )


def test_a_real_container_fails_the_injected_defect_then_passes_after_the_repair(client):
    app.dependency_overrides[get_sandbox] = lambda: DockerSandbox()
    client.llm.queue(*HAPPY_LLM)
    headers, task_id = new_task(client, "docker@example.com")
    assert client.post(f"{API}/tasks/{task_id}/start", headers=headers).status_code == 202

    task = client.get(f"{API}/tasks/{task_id}", headers=headers).json()
    its = iterations(client, headers, task_id)
    assert task["status"] == "COMPLETED", (task, its)
    assert [i["number"] for i in its] == [1, 2]
    # iteration 1: pytest really ran in a container and really failed on the injected defect
    assert its[0]["status"] == "failed_tests" and its[0]["tests"]["failed"] >= 1
    # iteration 2: the repaired code passes the whole suite, also inside a container
    assert its[1]["status"] == "accepted" and its[1]["tests"]["failed"] == 0
    assert its[1]["tests"]["total_tests"] >= its[0]["tests"]["total_tests"] > 0


def test_the_container_really_has_no_network(tmp_path):
    """Generated code cannot reach out: a socket connection attempt inside the sandbox fails."""
    work, out = tmp_path / "src", tmp_path / "out"
    work.mkdir()
    out.mkdir()
    (work / "probe.py").write_text(
        "import socket, sys\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('NETWORK-REACHABLE'); sys.exit(0)\n"
        "except OSError as exc:\n"
        "    print('NO-NETWORK', type(exc).__name__); sys.exit(1)\n"
    )
    from app.execution.sandbox import build_run_args

    cmd = build_run_args("loopforge-probe", work, out, ["python", "probe.py"])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert "NO-NETWORK" in r.stdout and "NETWORK-REACHABLE" not in r.stdout, r.stdout + r.stderr
