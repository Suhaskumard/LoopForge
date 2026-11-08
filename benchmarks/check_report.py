"""Check that docs/evaluation_report.md says exactly what the published trials say (Phase 14 gate).

    python benchmarks/check_report.py            # verify (exit 1 on any mismatch)
    python benchmarks/check_report.py --write    # regenerate the results block from the published run

The published run lives in `docs/evaluation/` (`manifest.json` + `trials.jsonl`, copied from a real run's output
directory). The report embeds `analyze.report(...)` for it between the markers below, so every number in that block is
recomputed here from `trials.jsonl` and compared character for character.

Two states are valid, nothing in between:
  * no published run  -> the block must say "To be measured" and contain no numbers; the report may not claim results.
  * a published run   -> the block equals the regenerated tables; the run must be real (not synthetic), cover E1, E2 and
                         E3, and its provenance must name a commit.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze  # noqa: E402

BEGIN = "<!-- results:begin -->"
END = "<!-- results:end -->"
NOT_RUN_TEXT = "To be measured"
REQUIRED_CONFIGS = {"E1", "E2", "E3"}


def extract_block(text: str) -> str | None:
    if BEGIN not in text or END not in text:
        return None
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip("\n")


def expected_block(published: Path) -> tuple[str | None, list[str]]:
    """The block the report must contain, and any reasons the published run is not acceptable."""
    problems: list[str] = []
    if not (published / "trials.jsonl").is_file() or not (published / "manifest.json").is_file():
        return None, problems
    manifest, rows = analyze.load(published)
    if not rows:
        problems.append("published trials.jsonl has no rows")
        return None, problems
    if manifest.get("synthetic") or any(r.get("synthetic") for r in rows):
        problems.append("published run is synthetic (oracle); only real-model runs may be published")
    missing = REQUIRED_CONFIGS - {r["config"] for r in rows}
    if missing:
        problems.append(f"published run lacks configuration(s) {sorted(missing)}")
    git = (manifest.get("provenance") or {}).get("git") or {}
    if not git.get("commit"):
        problems.append("manifest has no git commit in its provenance")
    return analyze.report(manifest, rows).strip("\n"), problems


def check(report_path: Path, published: Path) -> list[str]:
    if not report_path.is_file():
        return [f"{report_path} does not exist"]
    text = report_path.read_text(encoding="utf-8")
    block = extract_block(text)
    if block is None:
        return [f"report has no {BEGIN} ... {END} block"]
    want, problems = expected_block(published)
    if want is None:
        if not problems:
            if NOT_RUN_TEXT not in block:
                problems.append(f"no published run, so the results block must say {NOT_RUN_TEXT!r}")
            if any(ch.isdigit() for ch in block.replace("E1", "").replace("E2", "").replace("E3", "")):
                problems.append("no published run, so the results block must not contain any figures")
        return problems
    if not problems and block.strip() != want.strip():
        problems.append("results block differs from the tables recomputed from trials.jsonl (run with --write)")
    return problems


def write(report_path: Path, published: Path) -> None:
    want, problems = expected_block(published)
    if want is None or problems:
        raise SystemExit("cannot write: " + ("; ".join(problems) or "no published run in " + str(published)))
    text = report_path.read_text(encoding="utf-8")
    head, rest = text.split(BEGIN, 1)
    tail = rest.split(END, 1)[1]
    report_path.write_text(f"{head}{BEGIN}\n{want}\n{END}{tail}", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "docs" / "evaluation_report.md"))
    ap.add_argument("--published", default=str(ROOT / "docs" / "evaluation"))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    report, published = Path(args.report), Path(args.published)
    if args.write:
        write(report, published)
        print("results block regenerated")
        return 0
    problems = check(report, published)
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    if not problems:
        state = "published run matches" if (published / "trials.jsonl").is_file() else "no real run published (To be measured)"
        print(f"report check OK: {state}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
