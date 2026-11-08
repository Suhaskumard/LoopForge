"""Phase 12 security hardening: the checks that guard the repository stay in place and pass."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


def _ci() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _run_steps(job: dict) -> str:
    return "\n".join(
        f"{s.get('run', '')} {s.get('uses', '')} {s.get('with', '')}" for s in job["steps"]
    )


def test_bandit_finds_nothing_at_medium_or_high_severity():
    r = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", "app", "-ll", "-q"],
        cwd=BACKEND, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-2000:]


def test_bandit_low_findings_do_not_grow_unnoticed():
    """Accepted LOW findings (type-narrowing asserts, fixed-argv subprocess calls) are documented in
    docs/security_review.md; a new one means someone should look at it and update that list."""
    r = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", "app", "-q", "-f", "json"],
        cwd=BACKEND, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    totals = json.loads(r.stdout)["metrics"]["_totals"]
    assert totals["SEVERITY.HIGH"] == 0 and totals["SEVERITY.MEDIUM"] == 0
    assert (
        totals["SEVERITY.LOW"] <= 19
    ), "new low-severity bandit findings: review and update the budget"


def test_ci_runs_the_security_and_resilience_checks():
    ci = _ci()
    assert ci["permissions"] == {"contents": "read"}  # least privilege
    backend = _run_steps(ci["jobs"]["backend"])
    for needed in ("bandit -r app -ll", "chaos_drill.py", "backup_drill.py", "pytest -q -m slow"):
        assert needed in backend, needed
    supply = _run_steps(ci["jobs"]["supply-chain"])
    for needed in ("pip-audit", "requirements-runtime.txt", "npm audit", "--audit-level=high",
                   "cyclonedx", "upload-artifact", "trivy-action", "HIGH,CRITICAL"):  # fmt: skip
        assert needed in supply, needed


def test_ci_actions_are_pinned_to_a_version():
    for job in _ci()["jobs"].values():
        for step in job["steps"]:
            uses = step.get("uses")
            if uses:
                assert "@" in uses and not uses.endswith(("@main", "@master", "@latest")), uses


def test_ci_installs_dev_requirements_but_the_image_installs_runtime_only():
    ci_backend = _run_steps(_ci()["jobs"]["backend"])
    assert "pip install -r requirements.txt" in ci_backend  # tests/linters need the dev tools
    assert "requirements-runtime.txt" in (BACKEND / "Dockerfile").read_text(encoding="utf-8")


def test_the_local_scan_script_never_counts_a_skip_as_a_pass():
    text = (ROOT / "scripts" / "security_scan.sh").read_text(encoding="utf-8")
    assert "[SKIP]" in text and "not counted as passed" in text and "REQUIRE_AUDITS" in text
    assert "bandit -r app -ll" in text or "bandit -r app -ll -q" in text


def test_frontend_uses_a_react_router_without_the_known_advisories():
    deps = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))[
        "dependencies"
    ]
    assert (
        "react-router-dom" not in deps
    )  # 6.x had open-redirect advisories; v7 uses `react-router`
    major, minor, patch = (int(x) for x in deps["react-router"].split("."))
    assert (major, minor, patch) >= (
        7,
        18,
        5,
    ), f"react-router {deps['react-router']} has known advisories"


def test_security_documents_were_updated_for_phase_12():
    review = (ROOT / "docs" / "security_review.md").read_text(encoding="utf-8")
    model = (ROOT / "docs" / "security_model.md").read_text(encoding="utf-8")
    assert "Phase 12" in review and "Phase 12" in model
    assert "Phase 1 scope" not in model  # the stale title
    assert "Resume is guarded per process only" not in model  # superseded by run leases (ADR-0014)
