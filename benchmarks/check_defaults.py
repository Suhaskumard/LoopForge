"""Check that the defaults in the code match the decisions recorded in the evaluation report (Phase 14 gate).

    python benchmarks/check_defaults.py

The report carries one machine-readable comment:

    <!-- decisions: {"max_iterations": 5, "max_token_budget": 30000, "switches_off": ["p4"], "routing": {}} -->

Every key present is compared with the code; keys that are absent are not checked (no decision was taken).
  max_iterations, max_token_budget, max_attempts_per_failure, cost_per_1k_tokens -> Settings defaults
  routing      {"planner": "model-x", ...}  -> Settings.model_<agent> defaults ("" = the global model)
  switches_off ["history_retrieval", ...]   -> LoopConfig fields that must default to False (E3)
  switches_on  [...]                        -> LoopConfig fields that must default to True
An empty or missing block means "no decision yet" and passes: before the real run nothing may be claimed.
"""

import argparse
import dataclasses
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite://")

DECISIONS = re.compile(r"<!--\s*decisions:\s*(\{.*?\})\s*-->", re.S)
NUMERIC = ("max_iterations", "max_token_budget", "max_attempts_per_failure", "cost_per_1k_tokens")


def read_decisions(text: str) -> dict:
    m = DECISIONS.search(text)
    if not m:
        raise ValueError("report has no <!-- decisions: {...} --> block")
    return json.loads(m.group(1))


def check(decisions: dict) -> list[str]:
    from app.config import Settings
    from app.orchestrator.loop_config import LoopConfig

    problems: list[str] = []
    field_defaults = {f.name: f.default for f in dataclasses.fields(Settings)} if dataclasses.is_dataclass(Settings) else {
        n: f.default for n, f in Settings.model_fields.items()
    }
    for key in NUMERIC:
        if key in decisions and field_defaults.get(key) != decisions[key]:
            problems.append(f"{key}: report decides {decisions[key]!r}, code default is {field_defaults.get(key)!r}")
    for agent, model in (decisions.get("routing") or {}).items():
        code = field_defaults.get(f"model_{agent}")
        if code != model:
            problems.append(f"routing.{agent}: report decides {model!r}, code default is {code!r}")
    loop_defaults = {f.name: f.default for f in dataclasses.fields(LoopConfig)}
    for name in decisions.get("switches_off") or []:
        if name not in loop_defaults:
            problems.append(f"switches_off: unknown switch {name!r}")
        elif loop_defaults[name] is not False:
            problems.append(f"switches_off: {name} is still on by default in LoopConfig")
    for name in decisions.get("switches_on") or []:
        if name not in loop_defaults:
            problems.append(f"switches_on: unknown switch {name!r}")
        elif loop_defaults[name] is not True:
            problems.append(f"switches_on: {name} is off by default in LoopConfig")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "docs" / "evaluation_report.md"))
    args = ap.parse_args(argv)
    try:
        decisions = read_decisions(Path(args.report).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    problems = check(decisions)
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    if not problems:
        print(f"defaults check OK ({len(decisions)} decision key(s) compared)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
