# ruff: noqa: E501  (long explanatory strings and SQL/URL literals are clearer unwrapped in these tests)
"""Phase 13: bind-mount path translation for a worker that runs inside a container.

A worker in a container asks the HOST's Docker daemon to start the sandbox; the daemon resolves bind-mount sources
on the host, so a path like /data/workspaces/<task>/iter_1 (valid inside the worker) must become the matching
host path. These are pure tests of `to_host_path` / `build_run_args`: no Docker needed.
"""

import pytest

from app.config import settings
from app.execution.sandbox import (
    CONTAINER_OUT,
    CONTAINER_WORKSPACE,
    SandboxError,
    build_run_args,
    to_host_path,
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setattr(settings, "workspace_root", str(ws))
    return ws


def test_without_a_host_root_paths_are_unchanged(root, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", "")
    p = root / "t1" / "iter_1"
    assert to_host_path(p) == str(p)


@pytest.mark.parametrize("host_root", ["/srv/lf/ws", "/srv/lf/ws/", "/srv/lf/ws//"])
def test_a_path_under_the_workspace_root_moves_to_the_same_place_under_the_host_root(
    root, monkeypatch, host_root
):
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", host_root)
    assert to_host_path(root / "t1" / "iter_1") == "/srv/lf/ws/t1/iter_1"
    assert to_host_path(root / "t1" / "out" / "iter_2") == "/srv/lf/ws/t1/out/iter_2"
    assert to_host_path(root) == "/srv/lf/ws"


def test_paths_outside_the_workspace_root_are_refused(root, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", "/srv/lf/ws")
    for outside in (
        tmp_path / "elsewhere",
        root.parent / "workspaces-evil" / "t",
        root / ".." / "other",
    ):
        with pytest.raises(SandboxError, match="outside the workspace root"):
            to_host_path(outside)


def test_the_mount_uses_host_paths_but_the_container_side_does_not_change(root, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", "/srv/lf/ws")
    args = build_run_args("n", root / "t1" / "iter_1", root / "t1" / "out" / "iter_1", ["pytest"])
    mounts = [a for a in args if a.startswith("type=bind")]
    assert mounts == [
        f"type=bind,source=/srv/lf/ws/t1/iter_1,target={CONTAINER_WORKSPACE},readonly",
        f"type=bind,source=/srv/lf/ws/t1/out/iter_1,target={CONTAINER_OUT}",
    ]
    # the isolation flags are exactly what they were (translation must not touch them)
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "no-new-privileges"):
        assert flag in args
    assert not any(
        "/data/" in a or str(root) in a for a in mounts
    )  # no container-side path leaks to the daemon


def test_a_comma_in_the_translated_path_is_still_rejected(root, monkeypatch):
    """A comma would inject extra --mount options, whichever side of the translation it appears on."""
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", "/srv/lf,ws")
    with pytest.raises(SandboxError, match="unsupported character"):
        build_run_args("n", root / "t1", root / "t1" / "out", ["pytest"])
    monkeypatch.setattr(settings, "sandbox_host_workspace_root", "")
    with pytest.raises(SandboxError, match="unsupported character"):
        build_run_args("n", root / "a,b", root / "out", ["pytest"])


def test_the_default_configuration_translates_nothing():
    assert settings.sandbox_host_workspace_root == ""
