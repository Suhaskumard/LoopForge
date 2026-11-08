"""Phase 16: file deliverables (gate, ADR, held-out split, Go sandbox, honest docs)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _load(name: str, *parts: str):
    spec = importlib.util.spec_from_file_location(name, ROOT.joinpath(*parts))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_16_chains_gate_15_and_claims_nothing_unmeasured():
    gate = _read("scripts", "phase16_gate.sh")
    assert "scripts/phase15_gate.sh" in gate
    for needle in (
        "test_phase16_loop.py",
        "test_phase16_go.py",
        "validate_go.py",
        "check_defaults.py",
    ):
        assert needle in gate
    assert "NOT claimed" in gate and "does NOT" in gate
    make = _read("Makefile")
    assert "gate16:" in make and "gate16" in make.split(".PHONY:")[1].splitlines()[0]


def test_adr_is_honest_about_what_was_not_measured_or_built():
    adr = _read("docs", "adr", "0023-smarter-broader-loop.md")
    for needle in (
        "nothing measured on a real model",
        "Known limits",
        "never been compiled",
        "report-only",
        "learn_from_task",
        "PatchConflict",
        "noexec",
    ):
        assert needle in adr, needle
    assert "To be measured" in _read("docs", "evaluation_report.md")


def test_heldout_split_is_consistent():
    held = json.loads(_read("benchmarks", "heldout.json"))["tasks"]
    existing = {
        p.name
        for d in ("tasks", "tasks_phase8", "tasks_go")
        for p in (ROOT / "benchmarks" / d).iterdir()
    }
    assert set(held) <= existing and len(held) >= 5
    subset = json.loads(_read("benchmarks", "regression", "subset.json"))["tasks"]
    assert not set(held) & set(subset)
    runner = _read("benchmarks", "run_benchmarks.py")
    assert "--heldout" in runner and "--exclude-heldout" in runner


def test_check_defaults_rejects_a_phase_16_switch_turned_on_by_default(monkeypatch):
    mod = _load("check_defaults", "benchmarks", "check_defaults.py")
    assert mod.check({}) == []
    # a switch that IS on by default must be reported when it is declared a Phase 16 switch
    monkeypatch.setattr(mod, "PHASE16_SWITCHES", (*mod.PHASE16_SWITCHES, "reviewer_enabled"))
    assert any("reviewer_enabled" in p for p in mod.check({}))


def test_check_defaults_rejects_a_heldout_task_in_the_regression_subset(monkeypatch):
    mod = _load("check_defaults2", "benchmarks", "check_defaults.py")
    subset = json.loads(_read("benchmarks", "regression", "subset.json"))
    held = json.loads(_read("benchmarks", "heldout.json"))["tasks"][0]
    original = Path.read_text

    def fake_read(self, *a, **k):
        if self.name == "subset.json":
            return json.dumps({**subset, "tasks": [*subset["tasks"], held]})
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", fake_read)
    assert any(held in p for p in mod.check_heldout())


def test_go_sandbox_files_exist_and_forbid_modules_by_default():
    dockerfile = _read("backend", "sandbox", "go", "Dockerfile")
    assert "USER 10001" in dockerfile and "GOPROXY=off" in dockerfile and "UNTESTED" in dockerfile
    approved = [
        ln for ln in _read("backend", "sandbox", "go", "approved_modules.txt").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]  # fmt: skip
    assert approved == []


def test_validate_go_is_loud_when_it_cannot_run_the_behavioural_checks(monkeypatch, capsys):
    mod = _load("validate_go", "benchmarks", "validate_go.py")
    monkeypatch.setattr(mod, "go_command", lambda: None)
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out and "NOT been compiled" in out
    assert mod.main(["--require-go"]) == 1
