"""Phase 9 end to end with the synthetic oracle: the new presets run through the same loop and the
analysis reports the ablation table honestly. Proves wiring only, never that a feature helps."""

import json
import os
import subprocess
import sys
from pathlib import Path

from app.orchestrator.loop_config import E3, PRESETS

BENCH = Path(__file__).resolve().parents[3] / "benchmarks"
TASKS = "dv-01-isbn13,crud-01-employees"


def run(script, *args, timeout=900):
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "TEST_DATABASE_URL")}
    return subprocess.run(
        [sys.executable, str(BENCH / script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def test_presets_remove_exactly_the_switch_they_name():
    switches = ("failure_routing", "targeted_context", "test_guard", "history_retrieval")
    assert all(getattr(E3, s) for s in switches)  # production defaults: everything on
    assert not any(getattr(PRESETS["P0"], s) for s in switches)
    for name, switch in zip(("P1", "P2", "P3", "P4"), switches, strict=True):
        cfg = PRESETS[name]
        assert not getattr(cfg, switch)
        assert all(getattr(cfg, s) for s in switches if s != switch)
        # nothing else differs from E3, so a measured difference can only come from the switch
        assert cfg.max_iterations == E3.max_iterations and cfg.memory_enabled == E3.memory_enabled


def test_oracle_run_with_e3_and_phase9_ablations_and_table(tmp_path):
    out = tmp_path / "p9"
    r = run(
        "run_benchmarks.py",
        *("--config", "E3,P0,P2", "--trials", "2", "--provider", "oracle"),
        *("--tasks", TASKS, "--out", str(out)),
    )
    assert r.returncode == 0, r.stderr[-2000:]
    rows = [json.loads(x) for x in (out / "trials.jsonl").read_text().splitlines()]
    assert {x["config"] for x in rows} == {"E3", "P0", "P2"} and len(rows) == 3 * 2 * 2
    # the oracle's repairs are valid under every Phase 9 switch: each config can still repair
    for cfg in ("E3", "P0", "P2"):
        mine = [x for x in rows if x["config"] == cfg]
        assert any(x["iterations"] > 1 and x["success"] for x in mine), cfg

    report = run("analyze.py", str(out), "--allow-synthetic")
    assert report.returncode == 0, report.stderr[-2000:]
    assert "Phase 9 ablations" in report.stdout and "NOT A MEASUREMENT" in report.stdout
    assert "| P0 |" in report.stdout and "| P2 |" in report.stdout
    assert "| P1 | failure-class repair strategies | 0 | To be measured" in report.stdout  # noqa: E501
    # few trials: the intervals overlap, and the report must say so rather than claim a gain
    assert "not distinguishable from noise" in report.stdout
