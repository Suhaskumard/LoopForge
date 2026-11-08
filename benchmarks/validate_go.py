"""Validate the Go benchmark tasks (Phase 16).

Static checks always run (>=5 hidden tests, reference present, requirement names the module and the
signature, hidden test source not leaked). The behavioural checks need a Go toolchain: the reference
must pass its hidden tests and an EMPTY project must not. Without `go` those are SKIPPED loudly and
the exit code is 0 unless --require-go is given (CI that has Go should pass it).

    python benchmarks/validate_go.py [--require-go] [--tasks id1,id2]
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ROOT / "tasks_go"
MIN_TASKS = 10
MIN_TESTS = 5


def go_command() -> str | None:
    import os

    return os.environ.get("LOOPFORGE_GO") or shutil.which("go")


def run_go(go: str, project: Path | None, hidden: Path) -> tuple[int, int]:
    """(passed, total) of the hidden tests against `project` (None = an empty project)."""
    with tempfile.TemporaryDirectory(prefix="lf-go-") as tmp:
        work = Path(tmp)
        if project is not None and project.is_dir():
            shutil.copytree(project, work, dirs_exist_ok=True)
        else:
            (work / "go.mod").write_text("module example.com/task\n\ngo 1.22\n", encoding="utf-8")
        (work / "lib").mkdir(exist_ok=True)
        for f in hidden.glob("*_test.go"):
            shutil.copy(f, work / "lib" / f.name)
        proc = subprocess.run(
            [go, "test", "-json", "-count=1", "./..."],
            cwd=work, capture_output=True, text=True, timeout=240,
            env={**__import__("os").environ, "GOFLAGS": "-buildvcs=false", "GOPROXY": "off"},
        )  # fmt: skip
        passed = total = 0
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("Test") and ev.get("Action") in ("pass", "fail"):
                total += 1
                passed += ev["Action"] == "pass"
        return passed, total or 1


def static_problems(d: Path, meta: dict) -> list[str]:
    problems: list[str] = []
    hidden = d / "hidden_tests" / "hidden_test.go"
    if not hidden.is_file():
        return ["hidden_tests/hidden_test.go is missing"]
    text = hidden.read_text(encoding="utf-8")
    count = len(re.findall(r"^func Test\w+\(t \*testing\.T\)", text, re.M))
    if count < MIN_TESTS:
        problems.append(f"only {count} hidden tests (need >= {MIN_TESTS})")
    if not (d / "reference" / "go.mod").is_file() or not (d / "reference" / meta["module"]).is_file():
        problems.append("reference solution (go.mod and the module file) is missing")
    if meta["module"] not in meta["requirement"] or meta["signature"] not in meta["requirement"]:
        problems.append("requirement must name the module path and the exact signature")
    for line in text.splitlines():
        if line.startswith("func Test") and line.strip() in meta["requirement"]:
            problems.append("hidden test source leaked into the requirement")
    if meta.get("language") != "go" or meta.get("category") != "go":
        problems.append("task must declare language=go and category=go")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="")
    ap.add_argument("--require-go", action="store_true", help="fail instead of skipping without Go")
    args = ap.parse_args(argv)
    wanted = {t for t in args.tasks.split(",") if t}
    dirs = sorted(d for d in TASKS.iterdir() if d.is_dir() and (not wanted or d.name in wanted))
    go = go_command()
    if go is None:
        print("WARNING: no Go toolchain found (set LOOPFORGE_GO). Behavioural checks are SKIPPED:")
        print("         the reference solutions and hidden tests have NOT been compiled or run.")
    bad = 0
    for d in dirs:
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        problems = static_problems(d, meta)
        if go is not None and not problems:
            p, t = run_go(go, d / "reference", d / "hidden_tests")
            if p != t:
                problems.append(f"reference does not pass its hidden tests ({p}/{t})")
            p, t = run_go(go, None, d / "hidden_tests")
            if p == t:
                problems.append("an EMPTY project passes the hidden tests")
        label = "PASS" if not problems else "FAIL"
        suffix = "" if go is not None else " (static only)"
        print(f"  [{label}] {d.name}{suffix}" + "".join(f"\n        - {p}" for p in problems))
        bad += bool(problems)
    print(f"{len(dirs)} Go tasks; behavioural checks: {'run' if go else 'SKIPPED (no Go)'}")
    if not wanted and len(dirs) < MIN_TASKS:
        print(f"FAIL: need at least {MIN_TASKS} Go tasks", file=sys.stderr)
        return 1
    if go is None and args.require_go:
        print("FAIL: --require-go given but no Go toolchain was found", file=sys.stderr)
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
