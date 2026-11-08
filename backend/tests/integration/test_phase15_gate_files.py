"""Phase 15: the deliverables that are files (gate, CI job, Playwright setup, ADR, docs)."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_gate_15_chains_gate_14_and_states_what_it_does_not_cover():
    gate = _read("scripts", "phase15_gate.sh")
    assert "scripts/phase14_gate.sh" in gate
    for needle in ("test_phase15_accounts.py", "playwright test", "npm run lint", "SKIP_E2E"):
        assert needle in gate
    assert "does NOT" in gate or "does not" in gate.lower()
    make = _read("Makefile")
    assert "gate15:" in make and "e2e:" in make


def test_ci_has_an_e2e_job_with_a_mail_catcher():
    jobs = yaml.safe_load(_read(".github", "workflows", "ci.yml"))["jobs"]
    assert {"frontend", "e2e"} <= set(jobs)
    e2e = jobs["e2e"]
    assert "mailpit" in e2e["services"]
    steps = json.dumps(e2e["steps"])
    assert "playwright test" in steps and "test_phase15_smtp.py" in steps


def test_playwright_setup_covers_desktop_and_phone_and_axe():
    config = _read("frontend", "playwright.config.ts")
    assert "desktop" in config and "mobile" in config and "dev_demo_server.py" in config
    assert "VITE_DEV_AUTOLOGIN" in config  # tests must sign in themselves
    helpers = _read("frontend", "e2e", "helpers.ts")
    assert "AxeBuilder" in helpers and "serious" in helpers and "critical" in helpers
    pkg = json.loads(_read("frontend", "package.json"))
    assert "@playwright/test" in pkg["devDependencies"]
    assert "@axe-core/playwright" in pkg["devDependencies"]
    assert pkg["scripts"]["e2e"] == "playwright test"


def test_unit_test_runner_ignores_the_browser_specs():
    assert "e2e/**" in _read("frontend", "vite.config.ts")


def test_the_outbox_route_exists_only_in_the_demo_server():
    demo = _read("scripts", "dev_demo_server.py")
    assert "/__test__/outbox" in demo and 'E2E") == "1"' in demo
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        assert "/__test__/" not in path.read_text(encoding="utf-8"), path


def test_adr_and_docs_describe_phase_15():
    adr = _read("docs", "adr", "0022-product-experience.md")
    for needle in (
        "email_verified_at",
        "org_invites",
        "Known limits",
        "enumeration",
        "serious or critical",
        "created_by",
    ):
        assert needle in adr
    roadmap = _read("docs", "roadmap_phases_13_18.md")
    assert "Phase 15 is built" in roadmap and "ADR-0022" in roadmap
    assert "0010" in _read("docs", "database_schema.md")
    api = _read("docs", "api_documentation.md")
    for route in (
        "/auth/password-reset/request",
        "/invites/accept",
        "/auth/sessions",
        "/notifications",
    ):
        assert route in api
