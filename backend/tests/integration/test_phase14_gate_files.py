# ruff: noqa: E501  (long explanatory strings and assertions are clearer unwrapped in these tests)
"""Phase 14: the deliverables that are files (gate, CI, nightly workflow, ADR, README, honest report state)."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED = ROOT / "docs" / "evaluation" / "trials.jsonl"


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_gate_14_chains_gate_13_and_states_what_it_does_not_measure():
    gate = _read("scripts", "phase14_gate.sh")
    assert "scripts/phase13_gate.sh" in gate and "bench_regression.sh" in gate
    assert (
        "check_report.py" in gate and "check_defaults.py" in gate and "validate_phase8.py" in gate
    )
    assert "To be measured" in gate
    make = _read("Makefile")
    assert "gate14:" in make and "bench-regression:" in make and "bench-check:" in make


def test_ci_runs_the_regression_subset_and_both_checks():
    ci = _read(".github", "workflows", "ci.yml")
    assert "bench_regression.sh" in ci and "check_report.py" in ci and "check_defaults.py" in ci


def test_nightly_real_run_is_opt_in_and_budgeted():
    text = _read(".github", "workflows", "nightly-eval.yml")
    triggers = yaml.safe_load(text).get(True) or {}  # YAML 1.1 reads the key `on` as True
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    assert "NIGHTLY_MAX_COST" in text and "skipped" in text and "KIND: real" in text


def test_evaluation_report_makes_no_claim_without_a_published_run():
    report = _read("docs", "evaluation_report.md")
    assert "<!-- results:begin -->" in report and "<!-- decisions:" in report
    if not PUBLISHED.exists():
        block = report.split("<!-- results:begin -->")[1].split("<!-- results:end -->")[0]
        assert "To be measured" in block


def test_regression_baseline_is_not_invented():
    subset = json.loads(_read("benchmarks", "regression", "subset.json"))
    if not PUBLISHED.exists():
        assert subset["real"]["baseline_tsr_E3"] is None


def test_adr_and_readme_describe_phase_14():
    adr = _read("docs", "adr", "0021-measurement-tooling.md")
    for needle in (
        "paired",
        "tasks_phase8",
        "check_report.py",
        "check_defaults.py",
        "Known limits",
        "not measured",
        "Phase 16",
    ):
        assert needle in adr, needle
    readme = _read("README.md")
    assert "Phase 14" in readme and "gate14" in readme
