"""Phase 18: file deliverables (gate, ADR, honest wording)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_gate_18_chains_gate_17_and_runs_every_platform_check():
    gate = _read("scripts", "phase18_gate.sh")
    assert "scripts/phase17_gate.sh" in gate
    for needle in (
        "export_openapi.py --check",
        "test_phase18_contract.py",
        "test_phase18_limits_and_idempotency.py",
        "test_phase18_pagination.py",
        "test_phase18_sdk.py",
        "ts_sdk_contract.sh",
        "cli_install_check.sh",
        "upgrade_test.py",
        "--database-url",
        "build_docs.py",
    ):
        assert needle in gate, needle
    assert "does NOT" in gate and "FAILS the gate" in gate and "release CANDIDATE only" in gate
    make = _read("Makefile")
    assert "gate18:" in make and "gate18" in make.split(".PHONY:")[1].splitlines()[0]


def test_adr_states_scope_and_why_this_is_not_1_0_0():
    adr = _read("docs", "adr", "0025-platform-and-release-candidate.md")
    for needle in (
        "1.0.0-rc1",
        "Why not 1.0.0",
        "Deferred, not built",
        "Known limits",
        "LEGACY_SECRETS_KEY",
        "GitHub App",
    ):
        assert needle in adr, needle


def test_new_settings_are_in_env_example_and_the_api_policy_matches_the_defaults():
    env = _read(".env.example")
    for name in (
        "API_TOKEN_RATE_LIMIT_PER_MINUTE",
        "USER_RATE_LIMIT_PER_MINUTE",
        "IDEMPOTENCY_TTL_HOURS",
        "PLANS_JSON",
    ):
        assert name in env, name
    from app.config import Settings

    s = Settings()
    assert s.api_token_rate_limit_per_minute == 600 and s.idempotency_ttl_hours == 24
    policy = _read("docs", "api_policy.md")
    assert "600 requests/minute" in policy and "24 h" in policy


def test_roadmap_and_readme_record_phase_18_without_overclaiming():
    assert "Phase 18" in _read("README.md") and "release candidate" in _read("README.md").lower()
    road = _read("docs", "roadmap_phases_13_18.md")
    assert "1.0.0-rc1" in road and "not 1.0.0" in road
