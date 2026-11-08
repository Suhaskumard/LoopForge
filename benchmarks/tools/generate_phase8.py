"""Write benchmarks/tasks_phase8/ from catalog_phase8.py (deterministic; safe to re-run)."""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog_phase8 import JS_TASKS, REPO_TASKS  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tasks_phase8"
RUBRIC = {
    "primary": "all hidden tests pass (hidden_pass_rate == 1.0)",
    "notes": "hidden tests run in a separate, independent step; the agents' own tests do not count",
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def repo_task(t: dict) -> None:
    d = OUT / t["id"]
    mod = t["mod"]
    requirement = (
        "The Python repository you were given has a bug. Fix it in place so the behaviour described "
        "in SPEC holds. Keep every public function and its signature, keep the existing tests "
        "passing, and add a regression test that would have caught the bug.\n\n"
        f"SYMPTOM: {t['symptom']}\n\nSPEC: {t['spec']}\n\n"
        f"The code is in `lib/{mod}.py`; read it from the repository (it is not repeated here)."
    )
    meta = {
        "id": t["id"], "category": "repo_input", "language": "python", "difficulty": t["difficulty"],
        "requirement": requirement, "acceptance_criteria": [t["spec"]], "source": "repo",
        "rubric": RUBRIC,
    }  # fmt: skip
    write(d / "task.json", json.dumps(meta, indent=2) + "\n")
    for root, src in (("repo", t["broken"]), ("reference", t["fixed"])):
        write(d / root / "lib" / "__init__.py", "")
        write(d / root / "lib" / f"{mod}.py", src)
        write(d / root / "tests" / f"test_{mod}.py", t["visible"])
    write(d / "hidden_tests" / "test_hidden.py", t["hidden"])


def js_task(t: dict) -> None:
    d = OUT / t["id"]
    f = t["file"]
    requirement = (
        "Create a small Node.js (CommonJS) module tested with Jest. Put the implementation in "
        f"`src/{f}.js` and your own tests in `tests/{f}.test.js`; include a package.json "
        'whose only devDependency is "jest": "29.7.0". No other dependencies.\n\n'
        f"SPEC: {t['spec']}"
    )
    meta = {
        "id": t["id"], "category": "javascript", "language": "javascript",
        "difficulty": t["difficulty"], "requirement": requirement,
        "acceptance_criteria": [t["spec"]], "source": "none", "module": f"src/{f}.js",
        "rubric": RUBRIC,
    }  # fmt: skip
    write(d / "task.json", json.dumps(meta, indent=2) + "\n")
    write(d / "reference" / "package.json", '{"name": "ref", "devDependencies": {"jest": "29.7.0"}}\n')
    write(d / "reference" / "src" / f"{f}.js", t["ref"])
    write(d / "hidden_tests" / "hidden.test.js", t["test"])


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    for t in REPO_TASKS:
        repo_task(t)
    for t in JS_TASKS:
        js_task(t)
    print(f"wrote {len(REPO_TASKS)} repo + {len(JS_TASKS)} js tasks to {OUT}")


if __name__ == "__main__":
    main()
