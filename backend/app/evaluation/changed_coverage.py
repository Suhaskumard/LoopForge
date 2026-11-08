"""How much of the CHANGED code the tests execute (Phase 16, `changed_line_coverage`).

Overall coverage can stay high while the lines a repair just touched are never run. This joins the
lines that differ between two iterations with coverage.py's per-file executed/missing lines.
Report-only: it informs, it does not decide a verdict.
"""

import difflib
import json
from pathlib import Path
from typing import Any

PREFIXES = ("/workspace/", "workspace/")


def changed_lines(old_files: dict[str, str], new_files: dict[str, str]) -> dict[str, set[int]]:
    """1-based line numbers in the NEW version of each file that were added or modified."""
    out: dict[str, set[int]] = {}
    for path, new in new_files.items():
        old = old_files.get(path, "")
        if old == new:
            continue
        lines: set[int] = set()
        matcher = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                lines.update(range(j1 + 1, j2 + 1))
        if lines:
            out[path] = lines
    return out


def _norm(path: str) -> str:
    for prefix in PREFIXES:
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path.replace("\\", "/")


def read_line_coverage(path: Path) -> dict[str, tuple[set[int], set[int]]] | None:
    """{file: (executed lines, missing lines)} from coverage.py's JSON report, or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            _norm(name): (set(info["executed_lines"]), set(info["missing_lines"]))
            for name, info in data["files"].items()
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def changed_line_coverage(
    changed: dict[str, set[int]], coverage: dict[str, tuple[set[int], set[int]]]
) -> dict[str, Any]:
    """Counts only EXECUTABLE changed lines (blank lines and comments are neither)."""
    covered = executable = 0
    uncovered: dict[str, list[int]] = {}
    for path, lines in changed.items():
        if path not in coverage:
            continue  # tests, config and other files coverage.py did not measure
        executed, missing = coverage[path]
        hit, miss = lines & executed, lines & missing
        covered += len(hit)
        executable += len(hit) + len(miss)
        if miss:
            uncovered[path] = sorted(miss)[:20]
    return {
        "covered": covered,
        "executable": executable,
        "ratio": round(covered / executable, 4) if executable else None,
        "uncovered": uncovered,
    }
