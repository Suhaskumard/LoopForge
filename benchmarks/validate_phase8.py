"""Prove the Phase 8 benchmark tasks are sound (repo-input + JavaScript).

Repo-input tasks (`repo/`, `reference/`, `hidden_tests/`):
  1. the reference passes every hidden test (solvable, tests are right);
  2. the repository as given FAILS the hidden tests (the bug is real and detected);
  3. the repository's own visible tests PASS (it is a realistic working repo with a latent bug);
  4. an empty project fails; the requirement does not repeat the repository code or the hidden tests.

JavaScript tasks (`reference/`, `hidden_tests/hidden.test.js`): reference passes, empty project fails.
These need Jest. Set LOOPFORGE_JEST to a jest entry script (e.g. node_modules/jest/bin/jest.js) or
have `jest` on PATH. Without Jest the JS tasks are reported SKIP - never PASS.

    python benchmarks/validate_phase8.py [--tasks id1,id2] [--min-repo 10] [--min-js 10]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = Path(os.environ.get("LOOPFORGE_PHASE8_TASKS", ROOT / "tasks_phase8"))


def run_pytest(project: Path | None, tests: Path) -> tuple[int, int]:
    """Return (passed, total) for `tests` run against `project` (None = empty project)."""
    with tempfile.TemporaryDirectory(prefix="lf_p8_") as tmp:
        work = Path(tmp)
        if project is not None and project.is_dir():
            shutil.copytree(project, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests"))
        shutil.copytree(tests, work / "check_tests")
        report = work / "report.json"
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--json-report",
             f"--json-report-file={report}", "check_tests"],
            cwd=work, capture_output=True, text=True, timeout=120,
        )  # fmt: skip
        if not report.exists():
            return 0, 1
        s = json.loads(report.read_text(encoding="utf-8")).get("summary", {})
        return s.get("passed", 0), s.get("total", 0) or 1


def jest_command() -> list[str] | None:
    env = os.environ.get("LOOPFORGE_JEST")
    node = shutil.which("node")
    if env and node and Path(env).is_file():
        return [node, env]
    found = shutil.which("jest")
    return [found] if found else None


def run_jest(cmd: list[str], project: Path | None, tests: Path) -> tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="lf_p8js_") as tmp:
        work = Path(tmp)
        if project is not None and project.is_dir():
            shutil.copytree(project, work, dirs_exist_ok=True)
        (work / "tests").mkdir(exist_ok=True)
        for f in tests.glob("*.test.js"):
            shutil.copy(f, work / "tests" / f.name)
        out = work / "out.json"
        subprocess.run(
            [*cmd, "--ci", "--json", f"--outputFile={out}", "--rootDir", str(work), "--no-cache"],
            cwd=work, capture_output=True, text=True, timeout=180,
        )  # fmt: skip
        if not out.exists():
            return 0, 1
        data = json.loads(out.read_text(encoding="utf-8"))
        return int(data.get("numPassedTests", 0)), int(data.get("numTotalTests", 0)) or 1


def check_repo(d: Path, meta: dict) -> list[str]:
    problems: list[str] = []
    hidden = d / "hidden_tests"
    p, t = run_pytest(d / "reference", hidden)
    if t < 5 or p != t:
        problems.append(f"reference does not pass its hidden tests ({p}/{t})")
    p, t = run_pytest(d / "repo", hidden)
    if p == t:
        problems.append("the repository already passes the hidden tests - the bug is not detected")
    seed_visible = run_pytest(d / "repo", d / "repo" / "tests")
    if seed_visible[0] != seed_visible[1] or seed_visible[1] < 2:
        problems.append(f"the repository's own tests must pass and number >= 2 ({seed_visible})")
    p, t = run_pytest(None, hidden)
    if p == t:
        problems.append("an EMPTY project passes the hidden tests")
    for src in (d / "repo" / "lib").glob("*.py"):
        body = src.read_text(encoding="utf-8").strip()
        if len(body) > 20 and body in meta["requirement"]:
            problems.append(f"repository code {src.name} is repeated in the requirement")
    for line in (hidden / "test_hidden.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("def test_") and line.strip() in meta["requirement"]:
            problems.append("hidden test source leaked into the requirement")
    if meta.get("source") != "repo" or not (d / "repo").is_dir():
        problems.append("repo-input task must declare source=repo and ship a repo/ directory")
    return problems


def check_js(d: Path, meta: dict, cmd: list[str]) -> list[str]:
    problems: list[str] = []
    hidden = d / "hidden_tests"
    p, t = run_jest(cmd, d / "reference", hidden)
    if t < 5 or p != t:
        problems.append(f"reference does not pass its hidden tests ({p}/{t})")
    p, t = run_jest(cmd, None, hidden)
    if p == t:
        problems.append("an EMPTY project passes the hidden tests")
    if meta["module"] not in meta["requirement"]:
        problems.append("requirement does not name the module path")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="")
    ap.add_argument("--min-repo", type=int, default=10)
    ap.add_argument("--min-js", type=int, default=10)
    args = ap.parse_args()
    wanted = {t for t in args.tasks.split(",") if t}
    dirs = sorted(d for d in TASKS.iterdir() if d.is_dir() and (not wanted or d.name in wanted))
    jest = jest_command()
    bad = skipped = 0
    counts = {"repo_input": 0, "javascript": 0}
    for d in dirs:
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        cat = meta["category"]
        counts[cat] = counts.get(cat, 0) + 1
        if cat == "javascript" and jest is None:
            print(f"  [SKIP] {d.name} (Jest not available: set LOOPFORGE_JEST)")
            skipped += 1
            continue
        problems = check_repo(d, meta) if cat == "repo_input" else check_js(d, meta, jest or [])
        print(f"  [{'PASS' if not problems else 'FAIL'}] {d.name}" + "".join(f"\n        - {p}" for p in problems))
        bad += bool(problems)
    print(f"{len(dirs)} tasks: {counts}; {skipped} skipped")
    if not wanted and (counts["repo_input"] < args.min_repo or counts["javascript"] < args.min_js):
        print(f"FAIL: need >= {args.min_repo} repo-input and >= {args.min_js} javascript tasks")
        return 1
    if skipped:
        print(f"{skipped} JavaScript tasks were NOT validated (no Jest) - this is not a pass")
    print("ALL VALIDATED TASKS VALID" if not bad else f"{bad} INVALID TASKS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
