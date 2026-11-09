# ruff: noqa: E501
"""Phase 18: release engineering - one version everywhere, schema baselines, upgrade test, changelog, policies."""

import json
import re
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.version import __version__

ROOT = Path(__file__).resolve().parents[3]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _pep440(v: str) -> str:
    return v.replace("-rc", "rc")


def test_the_version_is_identical_in_every_place_that_states_it():
    assert re.fullmatch(r"\d+\.\d+\.\d+(-rc\d+)?", __version__)
    assert f'version = "{_pep440(__version__)}"' in _read("sdk", "python", "pyproject.toml")
    assert f'__version__ = "{_pep440(__version__)}"' in _read(
        "sdk", "python", "loopforge_sdk", "client.py"
    )
    ts = json.loads(_read("sdk", "typescript", "package.json"))["version"]
    assert ts == re.sub(r"rc(\d+)$", r"-rc.\1", _pep440(__version__)) or ts == __version__
    assert f'VERSION = "{_pep440(__version__)}"' in _read("sdk", "typescript", "src", "index.ts")
    assert f"## [{__version__}]" in _read("CHANGELOG.md")
    assert json.loads(_read("docs", "openapi.json"))["info"]["version"] == __version__


def test_schema_baselines_match_the_real_alembic_heads():
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    baselines = json.loads(_read("docs", "schema_baselines.json"))
    assert script.get_heads() == [baselines["current"]["head"]]
    previous = baselines["previous_release"]["head"]
    revisions = {r.revision for r in script.walk_revisions()}
    assert previous in revisions and previous != baselines["current"]["head"]
    # the previous head must be an ancestor of the current one (a straight upgrade path)
    chain = [r.revision for r in script.walk_revisions(base="base", head="heads")]
    assert chain.index(baselines["current"]["head"]) < chain.index(previous)


def test_changelog_and_policies_exist_and_are_honest_about_the_release_candidate():
    log = _read("CHANGELOG.md")
    assert "## [Unreleased]" in log and "Keep a Changelog" in log and "release candidate" in log
    guide = _read("docs", "upgrade_guide.md")
    for needle in ("back up first", "expand / contract", "LEGACY_SECRETS_KEY", "0011", "0013"):
        assert needle in guide, needle
    assert "unsupported" in _read("docs", "support_policy.md") and "SLA" in _read(
        "docs", "support_policy.md"
    )
    releasing = _read("docs", "releasing.md")
    assert "What blocks a 1.0.0" in releasing and "never yet run" in releasing
    policy = _read("docs", "api_policy.md")
    for needle in (
        "What is breaking",
        "Deprecation",
        "Idempotency-Key",
        "X-RateLimit-Limit",
        "X-Total-Count",
    ):
        assert needle in policy, needle


def test_the_upgrade_test_passes_from_the_previous_release_schema_with_data():
    """Runs scripts/upgrade_test.py on SQLite in a subprocess (Alembic is not thread-safe)."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "upgrade_test.py")],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert r.returncode == 0, r.stderr[-3000:]
    result = json.loads(r.stdout)
    assert result["from"] == "0011" and result["to"] == "0015", result
    assert all(result["checks"].values()), result["checks"]
    assert len(result["checks"]) >= 15  # the checks are substantial, not a stub
