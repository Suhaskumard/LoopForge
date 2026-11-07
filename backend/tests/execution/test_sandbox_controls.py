"""Spec §13.1 controls, verified on the exact `docker run` command line (no daemon needed)."""

from pathlib import Path

import pytest

from app.evaluation.test_runner import PYTEST_ARGV
from app.execution.runner import CommandNotAllowed, validate_command
from app.execution.sandbox import build_run_args


@pytest.fixture
def args():
    return build_run_args("n", Path("/ws/src"), Path("/ws/out"), PYTEST_ARGV)


def pair(args, flag):
    return args[args.index(flag) + 1]


def test_section_13_1_controls_present(args):
    assert pair(args, "--network") == "none"
    assert pair(args, "--user").split(":")[0] not in ("0", "root")
    assert "--read-only" in args
    assert pair(args, "--cap-drop") == "ALL"
    assert pair(args, "--security-opt") == "no-new-privileges"
    assert pair(args, "--memory").endswith("m")
    assert float(pair(args, "--cpus")) > 0 and int(pair(args, "--pids-limit")) > 0
    assert "--rm" in args  # explicit cleanup, backed by `docker rm -f` in the finally block


def test_only_task_directories_are_mounted_and_source_is_read_only(args):
    mounts = [a for a in args if a.startswith("type=bind")]
    assert len(mounts) == 2
    assert mounts[0].endswith("readonly") and f"source={Path('/ws/src')}," in mounts[0]
    joined = " ".join(args)
    forbidden_flags = ("docker.sock", "--privileged", "--network host", "--pid host", "--pid=host")
    for forbidden in (*forbidden_flags, "--volumes-from"):
        assert forbidden not in joined


@pytest.mark.parametrize(
    "argv",
    [
        ["sh", "-c", "id"],
        ["python", "-c", "print(1)"],
        ["python", "-m", "pip", "install", "x"],
        ["python", "-m", "pytest", "-p", "evil_plugin"],
        ["python", "-m", "pytest", "--rootdir=/etc"],
        ["python", "-m", "pytest", "/etc/passwd"],
        ["python", "-m", "pytest", "../x"],
        ["python", "-m", "pytest", "; rm -rf /"],
        ["python", "-m", "pytest", "--co", "-c", "x"],
        [],
    ],
)
def test_runner_rejects_non_allowlisted_commands(argv):
    with pytest.raises(CommandNotAllowed):
        validate_command(argv)


def test_runner_accepts_the_real_pytest_command():
    validate_command(PYTEST_ARGV)
    validate_command(["ruff", "check", "/workspace"])
