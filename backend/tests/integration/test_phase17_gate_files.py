"""Phase 17: file deliverables (gate, ADR, release workflow, pen-test package, honest docs)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_gate_17_chains_gate_16_and_claims_nothing_unmeasured():
    gate = _read("scripts", "phase17_gate.sh")
    assert "scripts/phase16_gate.sh" in gate
    for needle in (
        "security_regression.sh",
        "dr_drill.py",
        "load_postgres.sh",
        "test_phase17_backpressure.py",
    ):
        assert needle in gate
    assert "NOT done" in gate and "does NOT" in gate and "FAIL" in gate
    make = _read("Makefile")
    assert "gate17:" in make and "gate17" in make.split(".PHONY:")[1].splitlines()[0]


def test_adr_states_its_limits():
    adr = _read("docs", "adr", "0024-trust-at-scale.md")
    for needle in (
        "No external penetration test",
        "unmeasured",
        "fails closed",
        "never run",
        "RPO",
        "KeyUnavailable",
    ):
        assert needle in adr, needle


def test_pentest_package_claims_no_test_was_done():
    scope = _read("docs", "pentest", "scope.md")
    assert "No external penetration test has been performed" in scope
    assert (ROOT / "docs" / "pentest" / "findings_template.md").exists()


def test_release_workflow_is_least_privilege_and_admits_it_never_ran():
    text = _read(".github", "workflows", "release.yml")
    wf = yaml.safe_load(text)
    assert wf["permissions"] == {"contents": "read"}  # workflow default is read-only
    job = wf["jobs"]["image"]
    assert job["permissions"]["id-token"] == "write"  # only this job may mint the OIDC token
    assert "NEVER RUN" in text.upper().replace("HAS NEVER RUN", "NEVER RUN")
    ci = yaml.safe_load(_read(".github", "workflows", "ci.yml"))
    assert all("id-token" not in (j.get("permissions") or {}) for j in ci["jobs"].values())
    assert "--certificate-identity-regexp" in _read("scripts", "verify_image.sh")


def test_dependabot_covers_every_ecosystem_in_use():
    cfg = yaml.safe_load(_read(".github", "dependabot.yml"))
    assert {u["package-ecosystem"] for u in cfg["updates"]} == {
        "pip",
        "npm",
        "github-actions",
        "docker",
    }


def test_env_example_and_operations_document_the_new_settings():
    env = _read(".env.example")
    for name in (
        "KEYRING_JSON",
        "SANDBOX_RUNTIME",
        "MAX_QUEUED_JOBS",
        "OIDC_GROUP_ROLE_MAP_JSON",
        "WEBHOOK_ROTATION_OVERLAP_HOURS",
    ):
        assert name in env, name
    ops = _read("docs", "operations.md")
    for heading in (
        "## Key rotation",
        "## Disaster recovery drill",
        "## Queue back-pressure",
        "## SLOs and error budgets",
    ):
        assert heading in ops
