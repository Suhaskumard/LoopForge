"""Write benchmarks/tasks/<id>/ from the catalogs (the catalogs are the source of truth).

    python benchmarks/tools/generate_tasks.py

Layout per task:
    task.json           id, category, difficulty, requirement, acceptance_criteria, rubric
    hidden_tests/       pytest files that NO agent ever sees
    reference/          a known-good solution (used only to prove the task is solvable)
    seed/               (bug fixing) the broken starting code that is embedded in the requirement
"""

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import catalog_auth  # noqa: E402
import catalog_bugfix  # noqa: E402
import catalog_crud  # noqa: E402
import catalog_integration  # noqa: E402
import catalog_validation  # noqa: E402

TASKS_DIR = HERE.parent / "tasks"

RUBRIC = {
    "primary": "all hidden tests pass (hidden_pass_rate == 1.0)",
    "partial": "hidden_pass_rate is the fraction of hidden tests passed; reported separately",
    "notes": "hidden tests are executed in a separate, independent step; the agents' own tests do not count",
}


def all_tasks() -> list[dict]:
    tasks = (
        catalog_crud.tasks()
        + catalog_auth.tasks()
        + catalog_validation.tasks()
        + catalog_bugfix.tasks()
        + catalog_integration.tasks()
    )
    ids = [t["id"] for t in tasks]
    assert len(ids) == len(set(ids)), "duplicate task ids"
    return tasks


def write_files(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    if TASKS_DIR.exists():
        shutil.rmtree(TASKS_DIR)
    tasks = all_tasks()
    for t in tasks:
        d = TASKS_DIR / t["id"]
        meta = {k: t[k] for k in ("id", "category", "difficulty", "requirement", "acceptance_criteria")}
        meta["entrypoint"] = "app.main:app"
        meta["rubric"] = RUBRIC
        meta["has_seed"] = bool(t["seed"])
        d.mkdir(parents=True)
        (d / "task.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        write_files(d / "hidden_tests", {"test_hidden.py": t["hidden_test"]})
        write_files(d / "reference", t["reference"])
        if t["seed"]:
            write_files(d / "seed", t["seed"])
    by_cat: dict[str, int] = {}
    for t in tasks:
        by_cat[t["category"]] = by_cat.get(t["category"], 0) + 1
    print(f"wrote {len(tasks)} tasks to {TASKS_DIR}: {by_cat}")


if __name__ == "__main__":
    main()
