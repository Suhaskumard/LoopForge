"""Command runner (3.3): only allowlisted commands reach the sandbox; output is captured."""

import re
from pathlib import Path

from app.config import settings
from app.execution.sandbox import CONTAINER_OUT, CONTAINER_WORKSPACE, ExecResult, Sandbox


class CommandNotAllowed(Exception):
    pass


_SAFE_ARG = re.compile(r"^[A-Za-z0-9_./=:,\-]+$")
# Allowlisted command prefixes -> flags permitted after them (matched before any "=").
_ALLOWED: dict[tuple[str, ...], set[str]] = {
    ("python", "-m", "pytest"): {
        "-q",
        "-x",
        "-v",
        "--tb",
        "-p",
        "--json-report",
        "--json-report-file",
        "--rootdir",
        "--no-header",
    },  # fmt: skip
    ("ruff", "check"): {"--output-format", "--no-cache"},
}
_ALLOWED_P_VALUES = {"no:cacheprovider"}
_ROOTS = (CONTAINER_WORKSPACE, CONTAINER_OUT)


def validate_command(argv: list[str]) -> None:
    for prefix, flags in _ALLOWED.items():
        if tuple(argv[: len(prefix)]) == prefix:
            rest = argv[len(prefix) :]
            allowed_flags = flags
            break
    else:
        raise CommandNotAllowed(f"command not allowlisted: {argv[:3]}")
    for i, arg in enumerate(rest):
        if not _SAFE_ARG.match(arg) or ".." in arg.split("/"):
            raise CommandNotAllowed(f"unsafe argument: {arg!r}")
        if arg.startswith("-"):
            if arg.split("=", 1)[0] not in allowed_flags:
                raise CommandNotAllowed(f"flag not allowed: {arg!r}")
            value = arg.split("=", 1)[1] if "=" in arg else None
            if value and value.startswith("/") and not value.startswith(_ROOTS):
                raise CommandNotAllowed(f"path outside the sandbox mounts: {arg!r}")
        elif i > 0 and rest[i - 1] == "-p":
            if arg not in _ALLOWED_P_VALUES:
                raise CommandNotAllowed(f"pytest plugin not allowed: {arg!r}")
        elif arg.startswith("/") and not arg.startswith(_ROOTS):
            raise CommandNotAllowed(f"path outside the sandbox mounts: {arg!r}")


def run_command(
    sandbox: Sandbox, workspace: Path, out_dir: Path, argv: list[str], timeout: int | None = None
) -> ExecResult:
    validate_command(argv)
    return sandbox.run(workspace, out_dir, argv, timeout or settings.max_execution_seconds)
