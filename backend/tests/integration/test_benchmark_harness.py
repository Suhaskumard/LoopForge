"""The benchmark tooling end to end, as subprocesses (the runner sets its own database/workspace).

All runs use the synthetic `oracle` provider: they prove the harness works, not how good a model is.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[3] / "benchmarks"
TASKS = ["dv-01-isbn13", "crud-01-employees"]


def run(script, *args, env=None, timeout=900):
    e = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "TEST_DATABASE_URL")}
    e.update(env or {})
    return subprocess.run(
        [sys.executable, str(BENCH / script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=e,
    )


def trials(out):
    p = Path(out) / "trials.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.mark.slow
def test_all_thirty_tasks_are_valid_and_cover_five_categories():
    r = run("validate_tasks.py", timeout=1800)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "30 tasks" in r.stdout and "ALL TASKS VALID" in r.stdout
    for cat in ("crud", "authentication", "data_validation", "bug_fixing", "integration"):
        assert f"'{cat}': 6" in r.stdout


def _copy_task(tmp_path, name="dv-01-isbn13"):
    dst = tmp_path / "tasks"
    shutil.copytree(BENCH / "tasks" / name, dst / name)
    return dst


def test_validator_rejects_a_broken_reference(tmp_path):
    tasks = _copy_task(tmp_path)
    bad = tasks / "dv-01-isbn13/reference/app/validators.py"
    bad.write_text("def is_valid_isbn13(v):\n    return True\n")
    r = run("validate_tasks.py", "--min", "1", env={"LOOPFORGE_TASKS_DIR": str(tasks)})
    assert r.returncode == 1 and "reference does not pass" in r.stdout


def test_validator_rejects_hidden_tests_that_an_empty_project_passes(tmp_path):
    tasks = _copy_task(tmp_path)
    trivial = "".join(f"def test_{i}():\n    pass\n" for i in range(6))
    (tasks / "dv-01-isbn13/hidden_tests/test_hidden.py").write_text(trivial)
    r = run("validate_tasks.py", "--min", "1", env={"LOOPFORGE_TASKS_DIR": str(tasks)})
    assert r.returncode == 1 and "EMPTY project passes" in r.stdout


def test_validator_rejects_a_seed_that_already_passes(tmp_path):
    tasks = _copy_task(tmp_path, "bug-01-pagination")
    t = tasks / "bug-01-pagination"
    shutil.rmtree(t / "seed")
    shutil.copytree(t / "reference", t / "seed")
    r = run("validate_tasks.py", "--min", "1", env={"LOOPFORGE_TASKS_DIR": str(tasks)})
    assert r.returncode == 1 and "SEED already passes" in r.stdout


def test_dry_run_spends_nothing_and_states_the_ceiling(tmp_path):
    out = tmp_path / "o"
    r = run(
        "run_benchmarks.py",
        *("--config", "E1,E3", "--trials", "3", "--provider", "openai", "--dry-run"),
        *("--out", str(out)),
    )
    assert r.returncode == 0
    assert "2 config(s) x 30 task(s) x 3 trial(s) = 180 trials" in r.stdout
    assert "worst case" in r.stdout
    assert not (out / "trials.jsonl").exists()


def test_unknown_config_and_missing_key_are_refused(tmp_path):
    assert run("run_benchmarks.py", "--config", "E9", "--out", str(tmp_path / "a")).returncode == 2
    r = run(
        "run_benchmarks.py",
        *("--provider", "openai", "--tasks", TASKS[0], "--out", str(tmp_path / "b")),
        env={"OPENAI_API_KEY": ""},
    )
    assert r.returncode == 2 and "OPENAI_API_KEY" in r.stderr
    assert not (tmp_path / "b" / "trials.jsonl").exists()


def oracle_args(out, config="E1,E3", n="3"):
    return [
        *("--config", config, "--trials", n, "--provider", "oracle"),
        *("--tasks", ",".join(TASKS), "--out", str(out)),
    ]


def test_oracle_run_records_independent_hidden_results_and_is_resumable(tmp_path):
    out = tmp_path / "run"
    r = run("run_benchmarks.py", *oracle_args(out))
    assert r.returncode == 0, r.stderr[-2000:]
    assert "SYNTHETIC" in r.stdout
    rows = trials(out)
    assert len(rows) == 2 * 2 * 3 and all(x["synthetic"] for x in rows)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["synthetic"] is True and manifest["provider"] == "oracle"
    # success is decided by the hidden tests, never by the loop's own verdict
    for x in rows:
        all_pass = x["hidden_total"] > 0 and x["hidden_passed"] == x["hidden_total"]
        assert x["success"] == all_pass
    # the same trial uses the same defect in every configuration (a fair comparison)
    for task in TASKS:
        for t in range(3):
            modes = {x["oracle_mode"] for x in rows if x["task"] == task and x["trial"] == t}
            assert len(modes) == 1
    e1 = [x for x in rows if x["config"] == "E1"]
    e3 = [x for x in rows if x["config"] == "E3"]
    assert all(x["iterations"] == 1 for x in e1)
    assert sum(x["success"] for x in e3) >= sum(x["success"] for x in e1)
    assert any(x["iterations"] > 1 for x in e3)

    before = (out / "trials.jsonl").read_text()
    again = run("run_benchmarks.py", *oracle_args(out))
    assert again.returncode == 0 and (out / "trials.jsonl").read_text() == before


def test_token_cap_stops_the_run_and_it_can_resume(tmp_path):
    out = tmp_path / "capped"
    args = oracle_args(out, "E3", "2")
    r = run("run_benchmarks.py", *args, "--max-total-tokens", "1")
    assert r.returncode == 3 and "token cap" in r.stdout
    assert len(trials(out)) == 1  # the cap is checked before each trial
    assert run("run_benchmarks.py", *args).returncode == 0
    assert len(trials(out)) == 4


def test_analysis_of_a_harness_run(tmp_path):
    out = tmp_path / "an"
    run("run_benchmarks.py", *oracle_args(out, "E1,E2,E3", "2"))
    assert run("analyze.py", str(out)).returncode == 2  # synthetic is refused by default
    r = run("analyze.py", str(out), "--allow-synthetic")
    assert r.returncode == 0
    assert "NOT A MEASUREMENT" in r.stdout and "Task success rate (TSR)" in r.stdout
    assert "To be measured" in r.stdout  # A2-A4 were not run


def test_host_sandbox_is_only_wired_to_the_oracle_provider():
    src = (BENCH / "run_benchmarks.py").read_text()
    branch = src.split("else:\n        from app.execution.sandbox import DockerSandbox")[1]
    branch = branch.split("Base.metadata")[0]
    assert "HostSandbox" not in branch and "DockerSandbox()" in branch
