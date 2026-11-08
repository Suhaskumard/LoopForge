"""Turn trials.jsonl into the spec 12.4/12.5 results tables: mean, spread, CI, cost.

    python benchmarks/analyze.py benchmarks/results/run1 [--out report.md] [--allow-synthetic]

Rules (spec 12.5 / Addendum 21): report only measured values; never fold metrics into one score;
anything not run says "To be measured". Synthetic (oracle) runs are refused unless
--allow-synthetic is given, and are then stamped as harness checks on every table.

Definitions (per configuration, over all trials):
  TSR  task success rate          = successful trials / trials x 100   (success = ALL hidden tests pass)
  TPR  hidden test pass rate      = passed hidden tests / hidden tests executed x 100
  IE   iteration efficiency       = successful trials / total iterations used
  RR   regression proxy           = new failing test ids in later iterations / trials (upper bound:
                                    the system stores failures, not the full passing set)
  CPS  cost per success           = total estimated cost / successful trials
  FAR  false-accept rate          = trials the loop accepted (COMPLETED) but the hidden tests reject
Spread: when a configuration has >= 2 trials per task, TSR is computed once per repetition (all
tasks, trial k) and reported as mean +/- sample SD of those repetitions with a 95% t-interval;
the pooled Wilson interval over every trial is always given.
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

# two-sided 97.5% t quantiles for df = 1..30 (df > 30 uses the normal 1.96)
_T975 = [
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
]  # fmt: skip
ORDER = ["E1", "E2", "E3", "A1", "A2", "A3", "A4", "P0", "P1", "P2", "P3", "P4"]
PHASE9_REMOVED = {
    "P0": "ALL Phase 9 features (Phase 8 behaviour)",
    "P1": "failure-class repair strategies",
    "P2": "targeted Repair context",
    "P3": "test-weakening guard",
    "P4": "similar-repair retrieval",
}
NOT_RUN = "To be measured"


def t_crit(df: int) -> float:
    return _T975[df - 1] if 1 <= df <= 30 else 1.96


def mean_sd_ci(values: list[float]) -> tuple[float, float | None, tuple[float, float] | None]:
    """Mean, sample SD and 95% t-interval of the mean (SD/CI None below 2 samples)."""
    n = len(values)
    m = statistics.fmean(values)
    if n < 2:
        return m, None, None
    sd = statistics.stdev(values)
    half = t_crit(n - 1) * sd / math.sqrt(n)
    return m, sd, (m - half, m + half)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion (behaves at 0% and 100%, unlike the normal one)."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def load(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (run_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return manifest, rows


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    ok = [r for r in rows if r["success"]]
    executed = sum(r["hidden_total"] for r in rows)
    passed = sum(r["hidden_passed"] for r in rows)
    iters = sum(r["iterations"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    by_trial: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_trial[r["trial"]].append(r)
    reps = [sum(1 for r in g if r["success"]) / len(g) * 100 for g in by_trial.values()]
    lo, hi = wilson(len(ok), n)
    tsr_mean, tsr_sd, tsr_ci = mean_sd_ci(reps) if len(reps) >= 2 else (len(ok) / n * 100, None, None)
    tokens = [r["tokens"] for r in rows]
    secs = [r["seconds"] for r in rows]
    return {
        "n": n,
        "tasks": len({r["task"] for r in rows}),
        "repetitions": len(by_trial),
        "tsr": len(ok) / n * 100,
        "tsr_rep_mean": tsr_mean,
        "tsr_rep_sd": tsr_sd,
        "tsr_rep_ci": tsr_ci,
        "tsr_wilson": (lo * 100, hi * 100),
        "tpr": (passed / executed * 100) if executed else None,
        "avg_iterations": statistics.fmean(r["iterations"] for r in rows),
        "avg_iterations_success": statistics.fmean(r["iterations"] for r in ok) if ok else None,
        "ie": (len(ok) / iters) if iters else None,
        "rr": sum(r["regressions"] for r in rows) / n,
        "cps": (cost / len(ok)) if ok else None,
        "total_cost": cost,
        "tokens_mean": statistics.fmean(tokens),
        "tokens_sd": statistics.stdev(tokens) if n > 1 else None,
        "seconds_mean": statistics.fmean(secs),
        "seconds_sd": statistics.stdev(secs) if n > 1 else None,
        "false_accept": sum(1 for r in rows if r["false_accept"]) / n * 100,
        "loop_status": dict(Counter(r["loop_status"] for r in rows)),
        "failure_categories": dict(Counter(r["failure_category"] for r in rows if not r["success"])),
        "by_category": {
            c: (sum(1 for r in g if r["success"]), len(g))
            for c, g in _group(rows, "category").items()
        },
    }


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return dict(sorted(out.items()))


def fmt(v: float | None, digits: int = 1, suffix: str = "") -> str:
    return NOT_RUN if v is None else f"{v:.{digits}f}{suffix}"


def spread(mean: float, sd: float | None, ci: tuple[float, float] | None, suffix: str = "%") -> str:
    if sd is None or ci is None:
        return f"{mean:.1f}{suffix} (needs >= 2 repetitions for SD/CI)"
    lo, hi = max(0.0, ci[0]), min(100.0, ci[1])  # a percentage cannot leave 0-100
    return f"{mean:.1f}{suffix} +/- {sd:.1f} (95% CI {lo:.1f}-{hi:.1f}; wide when repetitions are few)"


def report(manifest: dict, rows: list[dict]) -> str:
    synthetic = manifest.get("synthetic", False)
    by_config = _group(rows, "config")
    configs = [c for c in ORDER if c in by_config] + [c for c in by_config if c not in ORDER]
    sums = {c: summarise(by_config[c]) for c in configs}
    out: list[str] = []
    if synthetic:
        out += [
            "> **SYNTHETIC HARNESS CHECK - NOT A MEASUREMENT.** These rows come from the `oracle` stand-in model",
            "> (reference solutions with injected defects). They show the pipeline works; they say nothing about",
            "> LoopForge or any real model.",
            "",
        ]
    out += [
        f"Provider `{manifest['provider']}`, model `{manifest['model']}`, started {manifest['started']}. "
        f"Cost = tokens x ${manifest['cost_per_1k_tokens']}/1k (an estimate).",
        f"Tasks: {len(manifest['tasks'])}; trials per task per configuration: {manifest['trials']}.",
        "",
        "## Results by configuration",
        "",
        "| Metric | " + " | ".join(ORDER[:3]) + " |",
        "|---|" + "---|" * 3,
    ]

    def row(label: str, f) -> str:
        cells = [f(sums[c]) if c in sums else NOT_RUN for c in ORDER[:3]]
        return f"| {label} | " + " | ".join(cells) + " |"

    out += [
        row("Trials", lambda s: str(s["n"])),
        row("Task success rate (TSR)", lambda s: f"{s['tsr']:.1f}%"),
        row("TSR, Wilson 95% interval (pooled)", lambda s: f"{s['tsr_wilson'][0]:.1f}-{s['tsr_wilson'][1]:.1f}%"),
        row("TSR across repetitions (mean +/- SD, 95% CI)", lambda s: spread(s["tsr_rep_mean"], s["tsr_rep_sd"], s["tsr_rep_ci"])),
        row("Test pass rate (TPR, hidden tests)", lambda s: fmt(s["tpr"], 1, "%")),
        row("Average iterations", lambda s: fmt(s["avg_iterations"], 2)),
        row("Iteration efficiency (IE)", lambda s: fmt(s["ie"], 3)),
        row("Regression proxy (new failing ids / trial)", lambda s: fmt(s["rr"], 2)),
        row("False-accept rate", lambda s: fmt(s["false_accept"], 1, "%")),
        row("Tokens per trial (mean +/- SD)", lambda s: f"{s['tokens_mean']:.0f}" + (f" +/- {s['tokens_sd']:.0f}" if s["tokens_sd"] is not None else "")),
        row("Time per trial (s, mean +/- SD)", lambda s: f"{s['seconds_mean']:.1f}" + (f" +/- {s['seconds_sd']:.1f}" if s["seconds_sd"] is not None else "")),
        row("Cost per success (CPS, estimate)", lambda s: fmt(s["cps"], 4, " USD") if s["cps"] is not None else "no successes"),
        row("Total estimated cost", lambda s: f"{s['total_cost']:.4f} USD"),
        "",
        "## Ablations (A1-A4) and E4-E6",
        "",
        "| Config | Removed component | Trials | TSR | TPR | Avg iterations | CPS |",
        "|---|---|---|---|---|---|---|",
    ]
    removed = {
        "A1": "independent Reviewer",
        "A2": "persistent iteration memory",
        "A3": "requirement verification",
        "A4": "adaptive retry",
    }
    for c in ("A1", "A2", "A3", "A4"):
        if c in sums:
            s = sums[c]
            out.append(f"| {c} | {removed[c]} | {s['n']} | {s['tsr']:.1f}% | {fmt(s['tpr'], 1, '%')} | {s['avg_iterations']:.2f} | {fmt(s['cps'], 4)} |")
        else:
            out.append(f"| {c} | {removed[c]} | 0 | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} |")
    if any(c in sums for c in PHASE9_REMOVED):
        out += [
            "",
            "## Phase 9 ablations (E3 = all Phase 9 features on)",
            "",
            "| Config | Removed | Trials | TSR (Wilson 95%) | Avg iterations | Tokens/trial | vs E3 |",
            "|---|---|---|---|---|---|---|",
        ]
        base = sums.get("E3")
        for c, what in PHASE9_REMOVED.items():
            if c not in sums:
                out.append(f"| {c} | {what} | 0 | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} | {NOT_RUN} |")
                continue
            r = sums[c]
            lo, hi = r["tsr_wilson"]
            if base is None:
                verdict = "no E3 run to compare with"
            elif lo <= base["tsr_wilson"][1] and base["tsr_wilson"][0] <= hi:
                verdict = "TSR difference not distinguishable from noise"
            else:
                verdict = "E3 better" if base["tsr"] > r["tsr"] else "E3 WORSE (feature hurts)"
            out.append(
                f"| {c} | {what} | {r['n']} | {r['tsr']:.1f}% ({lo:.1f}-{hi:.1f}) | "
                f"{r['avg_iterations']:.2f} | {r['tokens_mean']:.0f} | {verdict} |"
            )
        out += [
            "",
            "A feature that is not distinguishable from noise is reported as NOT shown to help; "
            "with few trials the intervals are wide and that is the expected result.",
        ]
    out += [
        "",
        "E4-E6 (Addendum 21.2: requirement traceability, adaptive repair, complete enhanced workflow) are not "
        "separate switches in this build: traceability, failure classification and repair history are part of "
        "E3 already, so they cannot be compared against an E3 without them. Reported as: not implemented as "
        "ablatable configurations.",
        "",
        "## Success by task category",
        "",
        "| Category | " + " | ".join(c for c in ORDER[:3]) + " |",
        "|---|" + "---|" * 3,
    ]
    cats = sorted({c for s in sums.values() for c in s["by_category"]})
    for cat in cats:
        cells = []
        for c in ORDER[:3]:
            ok, n = sums[c]["by_category"].get(cat, (0, 0)) if c in sums else (0, 0)
            cells.append(f"{ok}/{n}" if n else NOT_RUN)
        out.append(f"| {cat} | " + " | ".join(cells) + " |")
    out += ["", "## Failure categories (unsuccessful trials)", ""]
    for c in configs:
        cats_c = sums[c]["failure_categories"]
        out.append(f"- {c}: " + (", ".join(f"{k or 'unclassified'} x{v}" for k, v in sorted(cats_c.items())) or "none"))
    out += ["", "## Loop verdicts", ""]
    out += [f"- {c}: " + ", ".join(f"{k} {v}" for k, v in sorted(sums[c]["loop_status"].items())) for c in configs]
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out", default="")
    ap.add_argument("--allow-synthetic", action="store_true")
    args = ap.parse_args(argv)
    manifest, rows = load(Path(args.run_dir))
    if manifest.get("synthetic") and not args.allow_synthetic:
        print("refusing: this run used the synthetic oracle provider; pass --allow-synthetic for a harness report", file=sys.stderr)
        return 2
    if not rows:
        print("no trials recorded", file=sys.stderr)
        return 1
    text = report(manifest, rows)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
