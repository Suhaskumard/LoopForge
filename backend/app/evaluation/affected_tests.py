"""Which tests are affected by a change (Phase 16, `affected_tests_first`).

A cheap, conservative heuristic: a test is affected if it was itself changed, if its file name
mentions a changed module, or if its text imports one. It only decides what to run FIRST; the
full suite always runs before any verdict, so a miss here costs time, never correctness.
"""

import re
from pathlib import PurePosixPath

from app.execution.languages import LanguageProfile

MAX_AFFECTED = 20


def _module_patterns(path: str, language: str) -> list[re.Pattern[str]]:
    p = PurePosixPath(path)
    stem = p.stem
    if language == "python":
        dotted = ".".join(p.with_suffix("").parts)
        pats = [rf"(?:from|import)\s+{re.escape(dotted)}\b"]
        if len(p.parts) > 1:
            parent = ".".join(p.parent.parts)
            pats.append(rf"from\s+{re.escape(parent)}\s+import\s+[^\n]*\b{re.escape(stem)}\b")
        else:
            pats.append(rf"(?:from|import)\s+{re.escape(stem)}\b")
        return [re.compile(x) for x in pats]
    if language == "go":
        return []  # Go tests live in the package directory; handled by directory below
    return [
        re.compile(
            rf"""['"][^'"\n]*/{re.escape(stem)}(?:\.\w+)?['"]|['"]\./{re.escape(stem)}['"]"""
        )
    ]


def affected_tests(
    changed: list[str], files: dict[str, str], profile: LanguageProfile, limit: int = MAX_AFFECTED
) -> list[str]:
    """Test files to run first, sorted; empty when nothing can be tied to the change."""
    tests = [f for f in files if profile.is_test_file(f)]
    hit: set[str] = {c for c in changed if c in files and profile.is_test_file(c)}
    for path in changed:
        if profile.is_test_file(path) or not path.endswith(tuple(profile.source_extensions)):
            continue
        stem = PurePosixPath(path).stem
        patterns = _module_patterns(path, profile.name)
        for t in tests:
            same_dir = (
                profile.name == "go" and PurePosixPath(t).parent == PurePosixPath(path).parent
            )
            if (
                same_dir
                or stem in PurePosixPath(t).stem
                or any(p.search(files[t]) for p in patterns)
            ):
                hit.add(t)
    return sorted(hit)[:limit]
