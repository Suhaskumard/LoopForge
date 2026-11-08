"""Phase 12 real-evaluation kit: preflight finds every blocker; provenance is recorded."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BENCH = ROOT / "benchmarks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pre = _load("preflight")
prov = _load("provenance")


def good_env(**over) -> "pre.Env":
    env = pre.Env(
        environ={
            "OPENAI_API_KEY": "sk-secret-value-never-printed",
            "OPENAI_MODEL": "some-model",
            "COST_PER_1K_TOKENS": "0.004",
        },
        docker_reachable=True,
        images={"loopforge-sandbox"},
        task_dirs=[Path(f"t{i}") for i in range(30)],
        free_bytes=50_000_000_000,
        out_writable=True,
    )
    for k, v in over.items():
        setattr(env, k, v)
    return env


def run(env, provider="openai", cap=25.0, tokens=0, trials=3):
    return pre.run_checks(
        env, provider=provider, n_configs=3, n_tasks=30, trials=trials,
        token_budget=30000, max_total_cost=cap, max_total_tokens=tokens,
    )  # fmt: skip


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_a_fully_provisioned_real_run_passes_every_check():
    checks, ceiling = run(
        good_env(), cap=100.0
    )  # a cap above the worst case: nothing to warn about
    assert {c.status for c in checks} == {"PASS"}
    assert ceiling == pytest.approx(3 * 30 * 3 * 30000 / 1000 * 0.004)  # worst case, in USD


@pytest.mark.parametrize(
    ("override", "failing"),
    [
        (
            {"environ": {"OPENAI_MODEL": "m", "COST_PER_1K_TOKENS": "0.004"}},
            "OPENAI_API_KEY is set",
        ),
        (
            {"environ": {"OPENAI_API_KEY": "k", "COST_PER_1K_TOKENS": "0.004"}},
            "OPENAI_MODEL is set",
        ),
        (
            {"environ": {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m"}},
            "COST_PER_1K_TOKENS is set explicitly",
        ),
        (
            {"environ": {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m", "COST_PER_1K_TOKENS": "oops"}},
            "COST_PER_1K_TOKENS is set explicitly",
        ),
        (
            {"environ": {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m", "COST_PER_1K_TOKENS": "0"}},
            "COST_PER_1K_TOKENS is set explicitly",
        ),
        ({"docker_reachable": False}, "Docker daemon is reachable"),
        ({"images": set()}, "sandbox image 'loopforge-sandbox' exists"),
        ({"task_dirs": [Path("only-one")]}, "task set present (30 tasks)"),
        ({"out_writable": False}, "output directory is writable"),
        ({"free_bytes": 10_000}, "at least 1 GB free disk"),
    ],
)
def test_each_missing_prerequisite_is_a_blocker(override, failing):
    checks, _ = run(good_env(**override))
    assert statuses(checks)[failing] == "FAIL"
    assert [c.name for c in checks if c.status == "FAIL"] == [failing]  # and nothing else is blamed


def test_all_blockers_are_reported_together_not_one_at_a_time():
    checks, _ = run(good_env(environ={}, docker_reachable=False, images=set()), cap=0)
    failed = {c.name for c in checks if c.status == "FAIL"}
    assert failed >= {
        "OPENAI_API_KEY is set", "OPENAI_MODEL is set", "COST_PER_1K_TOKENS is set explicitly",
        "a spending cap is set",
        "Docker daemon is reachable",
        "sandbox image 'loopforge-sandbox' exists",
    }  # fmt: skip


def test_a_token_cap_alone_satisfies_the_spending_cap_check():
    checks, _ = run(good_env(), cap=0.0, tokens=1_000_000)
    assert statuses(checks)["a spending cap is set"] == "PASS"


def test_a_cap_below_the_worst_case_is_flagged_but_not_a_blocker():
    checks, ceiling = run(good_env(), cap=1.0)
    assert ceiling > 1.0
    warn = next(c for c in checks if c.name == "the cap covers the worst case")
    assert warn.status == "SKIP" and "may stop early" in warn.detail
    assert not [c for c in checks if c.status == "FAIL"]


def test_the_synthetic_provider_skips_real_run_checks_and_counts_none_as_passed():
    checks, _ = run(
        good_env(environ={}, docker_reachable=False, images=set()), provider="oracle", cap=0
    )
    st = statuses(checks)
    assert st["OPENAI_API_KEY is set"] == st["Docker daemon is reachable"] == "SKIP"
    assert not [c for c in checks if c.status == "FAIL"]


def test_the_api_key_value_is_never_printed(tmp_path):
    env = {
        **__import__("os").environ,
        "OPENAI_API_KEY": "sk-super-secret-12345",
        "OPENAI_MODEL": "m",
    }
    r = subprocess.run(
        [sys.executable, str(BENCH / "preflight.py"), "--out", str(tmp_path)],
        capture_output=True, text=True, env=env, timeout=120,
    )  # fmt: skip
    assert "sk-super-secret-12345" not in r.stdout + r.stderr
    assert r.returncode == 1 and "PREFLIGHT: FAIL" in r.stdout and "nothing was spent" in r.stdout


def test_oracle_preflight_exits_zero_and_says_what_was_skipped(tmp_path):
    r = subprocess.run(
        [sys.executable, str(BENCH / "preflight.py")]
        + ["--provider", "oracle", "--out", str(tmp_path)],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert (
        r.returncode == 0 and "PREFLIGHT: PASS" in r.stdout and "not counted as passed" in r.stdout
    )
    assert "[SKIP] OPENAI_API_KEY is set" in r.stdout


# ---- provenance ------------------------------------------------------------------------


def test_tree_hash_changes_when_any_task_file_changes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "task.json").write_text("{}")
    first = prov.tree_sha256(tmp_path)
    assert prov.tree_sha256(tmp_path) == first  # deterministic
    (tmp_path / "a" / "task.json").write_text('{"x": 1}')
    assert prov.tree_sha256(tmp_path) != first
    (tmp_path / "a" / "new.py").write_text("")
    assert prov.tree_sha256(tmp_path) not in {first}


def test_config_hash_changes_with_any_switch():
    from app.orchestrator.loop_config import E3, PRESETS

    base = prov.configs_sha256(PRESETS)
    assert prov.configs_sha256(PRESETS) == base
    changed = {**PRESETS, "E3": E3.__class__(**{**E3.__dict__, "reviewer_enabled": False})}
    assert prov.configs_sha256(changed) != base


def test_collect_records_commit_dirtiness_and_hashes():
    from app.orchestrator.loop_config import PRESETS

    info = prov.collect(BENCH / "tasks", PRESETS)
    assert set(info) == {
        "git",
        "tasks_sha256",
        "tasks_phase8_sha256",
        "settings_sha256",
        "loop_configs_sha256",
        "requirements_runtime_sha256",
        "python",
        "platform",
    }  # fmt: skip
    assert len(info["tasks_sha256"]) == 64 and len(info["loop_configs_sha256"]) == 64
    assert info["git"]["commit"] is None or len(info["git"]["commit"]) == 40
    assert info["git"]["dirty"] in (True, False, None)
    assert len(info["requirements_runtime_sha256"]) == 64


def test_the_harness_run_writes_provenance_into_its_manifest(tmp_path):
    out = tmp_path / "run"
    r = subprocess.run(
        [sys.executable, str(BENCH / "run_benchmarks.py"), "--config", "E3", "--trials", "1",
         "--provider", "oracle", "--tasks", "dv-01-isbn13", "--out", str(out)],
        capture_output=True, text=True, timeout=900,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr[-1500:]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["synthetic"] is True
    assert len(manifest["provenance"]["tasks_sha256"]) == 64
    assert "commit" in manifest["provenance"]["git"]


def test_documentation_points_at_the_one_command_and_keeps_results_unmeasured():
    report = (ROOT / "docs" / "evaluation_report.md").read_text(encoding="utf-8")
    assert "make eval" in report and "preflight" in report and "provenance" in report
    assert "no experiment has been run" in report.lower()
    assert "To be measured" in report
    assert (ROOT / "scripts" / "run_evaluation.sh").read_text(encoding="utf-8").count(
        "preflight.py"
    ) >= 1
