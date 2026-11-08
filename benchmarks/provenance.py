"""Reproducibility record for a benchmark run (Phase 12).

A result is only worth publishing if someone can tell exactly what produced it. The run manifest gets the
git commit (and whether the tree had uncommitted changes), hashes of the task set, the loop configurations and
the pinned requirements, and the interpreter/OS. Nothing here is a measurement and nothing is invented: a value
that cannot be determined is recorded as null, never guessed.
"""

import dataclasses
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_info() -> dict[str, object]:
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        # None = not a git checkout; True = results come from code that is not in any commit
        "dirty": None if status is None else bool(status),
    }


def tree_sha256(root: Path, patterns: tuple[str, ...] = ("*",)) -> str:
    h = hashlib.sha256()
    files = sorted({p for pat in patterns for p in root.rglob(pat) if p.is_file() and "__pycache__" not in p.parts})
    for p in files:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def configs_sha256(presets: dict) -> str:
    """Hash of every loop configuration (all switches), so a changed switch changes the hash."""
    payload = {name: dataclasses.asdict(cfg) for name, cfg in sorted(presets.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def settings_sha256(settings) -> str:
    """Hash of the settings that change results: models/routing, price map, iteration and token defaults."""
    keys = (
        "openai_model", "model_planner", "model_builder", "model_repair", "model_reviewer", "model_documentation",
        "model_prices_json", "cost_per_1k_tokens", "max_iterations", "max_token_budget",
        "max_attempts_per_failure", "max_execution_seconds",
    )  # fmt: skip
    payload = {k: getattr(settings, k, None) for k in keys}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def collect(tasks_dir: Path, presets: dict, phase8_dir: Path | None = None, settings=None) -> dict[str, object]:
    return {
        "git": git_info(),
        "tasks_sha256": tree_sha256(tasks_dir),
        "tasks_phase8_sha256": tree_sha256(phase8_dir) if phase8_dir is not None and phase8_dir.is_dir() else None,
        "settings_sha256": settings_sha256(settings) if settings is not None else None,
        "loop_configs_sha256": configs_sha256(presets),
        "requirements_runtime_sha256": file_sha256(ROOT / "backend" / "requirements-runtime.txt"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
