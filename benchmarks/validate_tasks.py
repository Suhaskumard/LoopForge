"""Prove every benchmark task is sound (spec 12.3: hidden acceptance tests per task).

For each task directory:
  1. the reference solution PASSES all hidden tests (the task is solvable and the tests are right);
  2. an EMPTY project fails them (the task is not trivially passable);
  3. for bug-fixing tasks, the SEED (broken code) fails them (the bug is real and detected);
  4. the hidden tests are not leaked into the requirement text;
  5. the requirement mentions the entry point.

The reference code is authored by us and trusted, so it runs in a plain subprocess (no sandbox);
generated code never takes this path - the runner uses the Sandbox interface for that.

    python benchmarks/validate_tasks.py [--tasks id1,id2] [--min 30]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = Path(os.environ.get("LOOPFORGE_TASKS_DIR", ROOT / "tasks"))
CATEGORIES = {"crud", "authentication", "data_validation", "bug_fixing", "integration"}


def run_hidden(project: Path, hidden: Path, timeout: int = 120) -> tuple[int, int, int]:
    """Copy project + hidden tests into a temp dir and run pytest. Returns (passed, failed, total)."""
    with tempfile.TemporaryDirectory(prefix="lf_validate_") as tmp:
        work = Path(tmp)
        if project.is_dir():
            shutil.copytree(project, work, dirs_exist_ok=True)
        shutil.copytree(hidden, work / "hidden_tests")
        report = work / "report.json"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--json-report",
             f"--json-report-file={report}", "hidden_tests"],
            cwd=work, capture_output=True, text=True, timeout=timeout,
        )  # fmt: skip
        if not report.exists():  # collection error / crash: everything counts as failed
            return 0, 1, 1
        s = json.loads(report.read_text(encoding="utf-8")).get("summary", {})
        total = s.get("total", 0)
        passed = s.get("passed", 0)
        if proc.returncode not in (0, 1) and total == 0:
            return 0, 1, 1
        return passed, total - passed, total


def check(task_dir: Path) -> list[str]:
    problems: list[str] = []
    meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    hidden = task_dir / "hidden_tests"
    if meta["category"] not in CATEGORIES:
        problems.append(f"unknown category {meta['category']}")
    if "app.main:app" not in meta["requirement"]:
        problems.append("requirement does not name the entry point app.main:app")
    if not meta["acceptance_criteria"]:
        problems.append("no acceptance criteria")
    leak = (hidden / "test_hidden.py").read_text(encoding="utf-8")
    for line in leak.splitlines():
        if re.match(r"\s*def test_\w+", line) and line.strip() in meta["requirement"]:
            problems.append("hidden test source leaked into the requirement")
            break

    p, f, t = run_hidden(task_dir / "reference", hidden)
    if t < 5 or f:
        problems.append(f"reference does not pass its hidden tests ({p}/{t} passed)")
    p0, f0, t0 = run_hidden(Path("/nonexistent"), hidden)
    if f0 == 0:
        problems.append("an EMPTY project passes the hidden tests")
    if meta["has_seed"]:
        ps, fs, ts = run_hidden(task_dir / "seed", hidden)
        if fs == 0:
            problems.append("the broken SEED already passes - the bug is not detected")
        for rel in (task_dir / "seed").rglob("*.py"):
            snippet = rel.read_text(encoding="utf-8")
            if snippet.strip() and snippet.strip() not in meta["requirement"]:
                problems.append(f"seed file {rel.name} is not shown in the requirement")
    elif (task_dir / "seed").exists():
        problems.append("unexpected seed directory")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="")
    ap.add_argument("--min", type=int, default=30)
    args = ap.parse_args()
    wanted = {t for t in args.tasks.split(",") if t}
    dirs = sorted(d for d in TASKS.iterdir() if d.is_dir() and (not wanted or d.name in wanted))
    bad = 0
    cats: dict[str, int] = {}
    for d in dirs:
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        cats[meta["category"]] = cats.get(meta["category"], 0) + 1
        problems = check(d)
        print(f"  [{'PASS' if not problems else 'FAIL'}] {d.name}" + "".join(f"\n        - {p}" for p in problems))
        bad += bool(problems)
    print(f"{len(dirs)} tasks, categories: {cats}")
    if not wanted and (len(dirs) < args.min or len(cats) < 5):
        print(f"FAIL: need >= {args.min} tasks across 5 categories")
        return 1
    print("ALL TASKS VALID" if not bad else f"{bad} INVALID TASKS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
