"""Regression benchmark gate (Phase 14): a small fixed subset that must not get worse.

    # CI, cheap, synthetic oracle (also what `make bench-regression` does):
    python benchmarks/run_benchmarks.py --provider oracle --config E1,E3 --trials 2 \
        --tasks <subset ids> --out /tmp/lf_regression
    python benchmarks/regression.py /tmp/lf_regression --kind oracle
    # nightly, budgeted, real model:
    python benchmarks/regression.py benchmarks/results/nightly --kind real

oracle: the pipeline still separates single-shot (E1) from the loop (E3) and never falsely accepts.
real:   E3's success rate on the subset has not dropped more than `tolerance_pp` below the measured baseline.
With no measured real baseline (null) the real check passes loudly with a notice - it never invents a threshold.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analyze  # noqa: E402

SUBSET = HERE / "regression" / "subset.json"


def load_subset(path: Path = SUBSET) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tsr(rows: list[dict], config: str) -> float | None:
    sub = [r for r in rows if r["config"] == config]
    return (sum(1 for r in sub if r["success"]) / len(sub) * 100) if sub else None


def false_accept(rows: list[dict], config: str) -> float:
    sub = [r for r in rows if r["config"] == config]
    return (sum(1 for r in sub if r["false_accept"]) / len(sub) * 100) if sub else 0.0


def check(rows: list[dict], subset: dict, kind: str) -> tuple[list[str], list[str]]:
    """(problems, notices). Problems fail the gate; notices are printed only."""
    problems: list[str] = []
    notices: list[str] = []
    expected = {(c, t) for c in subset["configs"] for t in subset["tasks"]}
    seen = {(r["config"], r["task"]) for r in rows}
    if expected - seen:
        problems.append(f"missing results for {sorted(expected - seen)}")
        return problems, notices
    e3, e1 = tsr(rows, "E3"), tsr(rows, "E1")
    if kind == "oracle":
        cfg = subset["oracle"]
        if e3 is None or e1 is None:
            problems.append("oracle check needs both E1 and E3 rows")
            return problems, notices
        if e3 < cfg["min_tsr_E3"]:
            problems.append(f"E3 success {e3:.1f}% fell below {cfg['min_tsr_E3']}%")
        if e3 - e1 < cfg["min_gap_E3_over_E1"]:
            problems.append(f"E3 beats E1 by only {e3 - e1:.1f} pp (need {cfg['min_gap_E3_over_E1']})")
        if false_accept(rows, "E3") > cfg["max_false_accept"]:
            problems.append(f"E3 false-accept rate {false_accept(rows, 'E3'):.1f}% is above {cfg['max_false_accept']}%")
    else:
        cfg = subset["real"]
        base = cfg["baseline_tsr_E3"]
        if base is None:
            notices.append("no measured real baseline yet (baseline_tsr_E3 is null): recorded, cannot alert")
            return problems, notices
        if e3 is None:
            problems.append("no E3 rows")
        elif e3 < base - cfg["tolerance_pp"]:
            problems.append(f"E3 success {e3:.1f}% dropped more than {cfg['tolerance_pp']} pp below the baseline {base}%")
        limit = cfg["max_false_accept"]
        if limit is not None and false_accept(rows, "E3") > limit:
            problems.append(f"E3 false-accept rate {false_accept(rows, 'E3'):.1f}% is above {limit}%")
    return problems, notices


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--kind", choices=["oracle", "real"], required=True)
    ap.add_argument("--subset", default=str(SUBSET))
    args = ap.parse_args(argv)
    manifest, rows = analyze.load(Path(args.run_dir))
    if args.kind == "oracle" and not manifest.get("synthetic"):
        print("FAIL: --kind oracle needs a synthetic run", file=sys.stderr)
        return 1
    if args.kind == "real" and manifest.get("synthetic"):
        print("FAIL: --kind real refuses a synthetic run", file=sys.stderr)
        return 1
    problems, notices = check(rows, load_subset(Path(args.subset)), args.kind)
    for n in notices:
        print(f"NOTICE: {n}")
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    if not problems:
        print(f"regression check OK ({args.kind})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
