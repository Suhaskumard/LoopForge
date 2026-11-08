# ruff: noqa: E501  (long explanatory strings and assertions are clearer unwrapped in these tests)
"""Phase 14: Phase 8 suite loading, noise verdicts, failure analysis, report/defaults checks, regression gate."""

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[3] / "benchmarks"
sys.path.insert(0, str(BENCH))

import analyze  # noqa: E402
import check_defaults  # noqa: E402
import check_report  # noqa: E402
import provenance  # noqa: E402
import regression  # noqa: E402
import run_benchmarks  # noqa: E402


def row(config="E3", task="t1", trial=0, success=True, **kw):
    base = {
        "config": config, "task": task, "category": "crud", "difficulty": "easy", "trial": trial,
        "provider": "openai", "model": "m", "oracle_mode": None,
        "loop_status": "COMPLETED" if success else "ESCALATED",
        "success": success, "hidden_total": 10, "hidden_passed": 10 if success else 4,
        "hidden_pass_rate": 1.0 if success else 0.4, "false_accept": False, "iterations": 2,
        "tokens": 1000, "cost": 0.002, "seconds": 10.0,
        "failure_category": "" if success else "execution",
        "regressions": 0, "synthetic": False,
    }  # fmt: skip
    return {**base, **kw}


MANIFEST = {
    "provider": "openai", "synthetic": False, "model": "m", "cost_per_1k_tokens": 0.002,
    "started": "now", "tasks": ["t1"], "trials": 2,
    "provenance": {"git": {"commit": "abc", "dirty": False}},
}  # fmt: skip


# ---- Phase 8 suite -----------------------------------------------------------------------------------


def test_core_suite_is_the_default_and_phase8_adds_twenty_tasks():
    core = run_benchmarks.load_tasks(Namespace(tasks="", category="", suite="core"))
    p8 = run_benchmarks.load_tasks(Namespace(tasks="", category="", suite="phase8"))
    both = run_benchmarks.load_tasks(Namespace(tasks="", category="", suite="all"))
    assert len(core) == 30 and len(p8) == 20 and len(both) == 50
    assert {t["language"] for t in core} == {"python"}
    assert sum(1 for t in p8 if t["language"] == "javascript") == 10
    assert sum(1 for t in p8 if t.get("source") == "repo") == 10
    assert len({t["id"] for t in both}) == 50


def test_oracle_refuses_phase8_tasks(capsys):
    code = run_benchmarks.main(
        ["--provider", "oracle", "--suite", "phase8", "--dry-run", "--out", "x"]
    )
    assert code == 2 and "real provider" in capsys.readouterr().err


def test_dry_run_counts_phase8_tasks(capsys):
    argv = [
        "--provider",
        "openai",
        "--suite",
        "all",
        "--config",
        "E1,E2,E3",
        "--trials",
        "3",
        "--dry-run",
        "--out",
        "x",
    ]
    assert run_benchmarks.main(argv) == 0
    assert "450 trials" in capsys.readouterr().out


# ---- manifest ----------------------------------------------------------------------------------------


def test_settings_hash_changes_with_the_price_map_and_defaults():
    a = Namespace(model_prices_json="", max_iterations=5)
    b = Namespace(model_prices_json='{"m": 0.1}', max_iterations=5)
    c = Namespace(model_prices_json="", max_iterations=6)
    assert len({provenance.settings_sha256(x) for x in (a, b, c)}) == 3
    assert provenance.settings_sha256(a) == provenance.settings_sha256(
        Namespace(model_prices_json="", max_iterations=5)
    )


def test_collect_records_phase8_and_settings_hashes():
    from app.config import settings
    from app.orchestrator.loop_config import PRESETS

    info = provenance.collect(
        run_benchmarks.TASKS_DIR, PRESETS, run_benchmarks.PHASE8_DIR, settings
    )
    assert len(info["tasks_phase8_sha256"]) == 64 and len(info["settings_sha256"]) == 64


# ---- analysis ----------------------------------------------------------------------------------------


def _tasks(config, outcomes):
    return [row(config, task=f"t{i}", success=ok) for i, ok in enumerate(outcomes)]


def test_paired_difference_matches_hand_computation():
    base = _tasks("E3", [True, True, True, False])
    other = _tasks("A1", [True, True, False, False])
    m, ci, n = analyze.paired_difference(base, other)
    # per-task diffs (pp): 0, 0, 100, 0 -> mean 25, sd 50, t(3)=3.182 -> half = 3.182*50/2
    assert (m, n) == (25.0, 4)
    assert ci == pytest.approx((25 - 79.55, 25 + 79.55), abs=0.01)


def test_verdicts_distinguish_help_noise_and_harm():
    off = _tasks("A1", [False, False, False, True, False, False, False, False])
    assert "feature helps" in analyze.switch_verdict(_tasks("E3", [True] * 8), off)
    noise = analyze.switch_verdict(
        _tasks("E3", [True, True, True, False]), _tasks("A1", [True, True, False, False])
    )
    assert "not distinguishable from noise" in noise
    assert "HURTS" in analyze.switch_verdict(_tasks("E3", [False] * 8), _tasks("A1", [True] * 8))
    assert "needs >= 2 shared tasks" in analyze.switch_verdict(
        _tasks("E3", [True]), _tasks("A1", [True])
    )


def test_report_has_noise_section_failure_analysis_and_cost_per_solved_task():
    rows = [
        row("E1", success=False), row("E2", success=True),
        *_tasks("E3", [True, True, False, True]), *_tasks("A1", [True, False, False, True]),
    ]  # fmt: skip
    text = analyze.report(MANIFEST, rows)
    assert "Is each component distinguishable from noise" in text and "- A1:" in text
    assert "## Failure analysis (E3)" in text and "Tasks solved in fewer than half" in text
    assert "Cost per solved task" in text


# ---- report vs trials --------------------------------------------------------------------------------


def _publish(tmp_path, rows=None, manifest=None):
    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "manifest.json").write_text(json.dumps(manifest or MANIFEST), encoding="utf-8")
    rows = rows or [row(c, trial=t) for c in ("E1", "E2", "E3") for t in (0, 1)]
    (pub / "trials.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return pub


def _report(tmp_path, block):
    p = tmp_path / "report.md"
    p.write_text(
        f"head\n{check_report.BEGIN}\n{block}\n{check_report.END}\ntail\n", encoding="utf-8"
    )
    return p


def test_the_real_report_passes_with_no_published_run():
    root = check_report.ROOT
    assert (
        check_report.check(root / "docs" / "evaluation_report.md", root / "docs" / "evaluation")
        == []
    )


def test_no_run_means_no_figures_allowed(tmp_path):
    assert check_report.check(_report(tmp_path, "**To be measured.**"), tmp_path / "none") == []
    assert check_report.check(_report(tmp_path, "To be measured, TSR is 83.3%"), tmp_path / "none")
    assert check_report.check(_report(tmp_path, "all good"), tmp_path / "none")


def test_written_block_verifies_and_a_tampered_number_fails(tmp_path):
    pub = _publish(tmp_path)
    report = _report(tmp_path, "To be measured")
    assert check_report.check(report, pub)  # stale block
    check_report.write(report, pub)
    assert check_report.check(report, pub) == []
    report.write_text(
        report.read_text(encoding="utf-8").replace("100.0%", "99.0%", 1), encoding="utf-8"
    )
    assert any("differs" in p for p in check_report.check(report, pub))


def test_synthetic_or_incomplete_publications_are_refused(tmp_path):
    pub = _publish(tmp_path, manifest={**MANIFEST, "synthetic": True})
    assert any("synthetic" in p for p in check_report.check(_report(tmp_path, "x"), pub))
    pub2 = tmp_path / "p2"
    pub2.mkdir()
    (pub2 / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (pub2 / "trials.jsonl").write_text(json.dumps(row("E3")), encoding="utf-8")
    assert any("lacks configuration" in p for p in check_report.check(_report(tmp_path, "x"), pub2))


# ---- defaults vs decisions ---------------------------------------------------------------------------


def test_defaults_check_passes_for_matching_and_empty_decisions():
    assert check_defaults.check({}) == []
    from app.config import Settings

    assert (
        check_defaults.check(
            {"max_iterations": Settings().max_iterations, "switches_on": ["failure_routing"]}
        )
        == []
    )
    assert check_defaults.main([]) == 0


def test_defaults_check_catches_mismatches():
    problems = check_defaults.check(
        {
            "max_iterations": 99,
            "switches_off": ["history_retrieval", "nonsense"],
            "switches_on": ["reviewer_enabled"],
            "routing": {"planner": "gpt-x"},
        }
    )
    text = "\n".join(problems)
    assert "max_iterations" in text and "history_retrieval is still on" in text
    assert "unknown switch 'nonsense'" in text and "routing.planner" in text
    assert "reviewer_enabled" not in text


def test_decisions_block_is_required():
    with pytest.raises(ValueError):
        check_defaults.read_decisions("nothing here")


# ---- regression gate ---------------------------------------------------------------------------------


def _reg_rows(e3_ok, e1_ok, fa=False):
    subset = regression.load_subset()
    rows = []
    for i, t in enumerate(subset["tasks"]):
        rows.append(row("E3", task=t, success=i < e3_ok, false_accept=fa and i == 0))
        rows.append(row("E1", task=t, success=i < e1_ok))
    return rows, subset


def test_regression_subset_tasks_exist():
    ids = {
        t["id"] for t in run_benchmarks.load_tasks(Namespace(tasks="", category="", suite="core"))
    }
    assert set(regression.load_subset()["tasks"]) <= ids


def test_oracle_regression_passes_and_catches_drops():
    rows, subset = _reg_rows(5, 2)
    assert regression.check(rows, subset, "oracle") == ([], [])
    low, _ = _reg_rows(2, 1)
    assert regression.check(low, subset, "oracle")[0]
    gap, _ = _reg_rows(5, 5)
    assert any("only" in p for p in regression.check(gap, subset, "oracle")[0])
    fa, _ = _reg_rows(5, 2, fa=True)
    assert any("false-accept" in p for p in regression.check(fa, subset, "oracle")[0])
    assert regression.check(rows[:-1], subset, "oracle")[0][0].startswith("missing")


def test_real_regression_needs_a_measured_baseline_and_never_invents_one():
    rows, subset = _reg_rows(5, 2)
    assert subset["real"]["baseline_tsr_E3"] is None
    problems, notices = regression.check(rows, subset, "real")
    assert problems == [] and "no measured real baseline" in notices[0]
    subset["real"]["baseline_tsr_E3"] = 90.0
    drop, _ = _reg_rows(3, 1)  # 50% < 90 - 15
    assert regression.check(drop, subset, "real")[0]
    assert regression.check(rows, subset, "real")[0] == []  # 83% >= 75
