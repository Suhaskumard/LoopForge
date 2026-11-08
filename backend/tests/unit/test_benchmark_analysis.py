"""benchmarks/analyze.py: the statistics are checked against hand-computed values."""

import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[3] / "benchmarks"
sys.path.insert(0, str(BENCH))

import analyze  # noqa: E402


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
}  # fmt: skip


def test_t_quantiles_match_published_values():
    assert analyze.t_crit(1) == pytest.approx(12.706)
    assert analyze.t_crit(4) == pytest.approx(2.776)
    assert analyze.t_crit(30) == pytest.approx(2.042)
    assert analyze.t_crit(100) == pytest.approx(1.96)


def test_mean_sd_ci_hand_computed():
    m, sd, ci = analyze.mean_sd_ci([60.0, 70.0, 80.0])
    assert m == pytest.approx(70.0) and sd == pytest.approx(10.0)
    half = 4.303 * 10.0 / math.sqrt(3)
    assert ci == pytest.approx((70 - half, 70 + half))


def test_single_sample_has_no_spread():
    assert analyze.mean_sd_ci([5.0]) == (5.0, None, None)


def test_wilson_interval_known_values():
    lo, hi = analyze.wilson(8, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.490, 0.943)
    lo0, hi0 = analyze.wilson(0, 10)
    assert lo0 == 0.0 and 0.2 < hi0 < 0.35
    lo1, hi1 = analyze.wilson(10, 10)
    assert hi1 == 1.0 and lo1 > 0.65
    assert analyze.wilson(0, 0) == (0.0, 0.0)


def test_summary_metrics():
    rows = [
        row(task="a", trial=0),
        row(task="b", trial=0, success=False, iterations=5, tokens=3000, cost=0.006),
        row(task="a", trial=1),
        row(task="b", trial=1),
    ]
    s = analyze.summarise(rows)
    assert s["n"] == 4 and s["tsr"] == 75.0 and s["repetitions"] == 2
    assert s["tpr"] == pytest.approx((10 + 4 + 10 + 10) / 40 * 100)
    assert s["ie"] == pytest.approx(3 / (2 + 5 + 2 + 2))
    assert s["cps"] == pytest.approx((0.002 * 3 + 0.006) / 3)
    assert s["avg_iterations"] == pytest.approx(2.75) and s["avg_iterations_success"] == 2
    # repetition TSRs are 50% (trial 0) and 100% (trial 1)
    assert s["tsr_rep_mean"] == pytest.approx(75.0)
    assert s["tsr_rep_sd"] == pytest.approx(35.355, abs=1e-3)
    assert s["failure_categories"] == {"execution": 1}
    assert s["by_category"] == {"crud": (3, 4)}


def test_no_successes_means_no_cost_per_success():
    s = analyze.summarise([row(success=False), row(task="t2", success=False)])
    assert s["cps"] is None and s["ie"] == 0 and s["tsr"] == 0


def test_false_accept_rate():
    bad = row(false_accept=True, success=False, loop_status="COMPLETED")
    assert analyze.summarise([bad, row(task="x")])["false_accept"] == 50.0


def test_report_marks_unrun_configs_as_to_be_measured():
    text = analyze.report(MANIFEST, [row(), row(trial=1)])
    assert "To be measured" in text and "| A1 | independent Reviewer | 0 |" in text
    assert "SYNTHETIC" not in text
    assert "not implemented as ablatable configurations" in text


def test_percentage_intervals_are_clipped_to_0_100():
    text = analyze.spread(50.0, 70.7, (-100.0, 200.0))
    assert "95% CI 0.0-100.0" in text


def test_one_repetition_is_honest_about_missing_spread():
    text = analyze.report(MANIFEST, [row(), row(task="t2")])
    assert "needs >= 2 repetitions" in text


def test_synthetic_runs_are_stamped_and_refused_by_default(tmp_path, capsys):
    synthetic = {**MANIFEST, "synthetic": True, "provider": "oracle"}
    (tmp_path / "manifest.json").write_text(json.dumps(synthetic))
    (tmp_path / "trials.jsonl").write_text(json.dumps(row(synthetic=True)) + "\n")
    assert analyze.main([str(tmp_path)]) == 2
    assert "refusing" in capsys.readouterr().err
    assert analyze.main([str(tmp_path), "--allow-synthetic", "--out", str(tmp_path / "r.md")]) == 0
    assert "NOT A MEASUREMENT" in (tmp_path / "r.md").read_text()
