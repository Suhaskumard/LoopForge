"""Failure classes (Phase 9, ADR-0016): *what kind* of failure this is, so Repair can be steered.

`classifier.py` tags the feedback *channel* (execution / quality / requirement). This module looks
at the execution failures and names the cause family. It is deterministic and conservative: when
nothing specific matches, the class is `logic`, the generic "the implementation is wrong" strategy.
"""

import re
from typing import Any, Literal

from app.execution.languages import PYTHON, LanguageProfile

FailureClass = Literal["syntax", "import", "environment", "test_wrong", "logic"]

_SYNTAX = frozenset({"SyntaxError", "IndentationError", "TabError"})
_IMPORT = frozenset({"ImportError", "ModuleNotFoundError"})
_ENVIRONMENT = frozenset({"Timeout", "MemoryError", "OSError", "PermissionError"})
_SYNTHETIC_ENVIRONMENT = ("<dependencies>", "<execution>")
_JS_SYNTAX = re.compile(r"SyntaxError|Unexpected token|Unexpected identifier", re.I)
_JS_IMPORT = re.compile(r"Cannot find module|Module not found|ERR_MODULE_NOT_FOUND", re.I)
_PATHS = re.compile(r"([\w./\\-]+\.(?:py|mjs|cjs|jsx?|tsx?))")

STRATEGIES: dict[str, str] = {
    "syntax": (
        "The code does not parse. Fix only the syntax error(s) named in the report; "
        "do not change behaviour."
    ),
    "import": (
        "A module or name cannot be imported. Check file names, package layout and the names being "
        "imported. Do NOT add dependencies that are not already allowed."
    ),
    "environment": (
        "The run failed for an environment reason (timeout, missing report, dependency install). "
        "Look for infinite loops, blocking calls, or work done at import time; do not rewrite "
        "working logic."
    ),
    "test_wrong": (
        "The failure is inside the tests themselves (fixture/setup/collection error), not in the "
        "implementation. Correct the test only if it is clearly wrong, and keep every test and its "
        "assertions at least as strict as before."
    ),
    "logic": (
        "The implementation behaves incorrectly. Find the root cause in the implementation (not "
        "the tests) and fix it with the smallest change."
    ),
}


def _is_test_path(path: str, profile: LanguageProfile) -> bool:
    return profile.is_test_file(path.replace("\\", "/").lstrip("./"))


def _one(failure: dict[str, Any], profile: LanguageProfile) -> FailureClass:
    nodeid = str(failure.get("nodeid", failure.get("test", "")))
    error_type = str(failure.get("error_type", ""))
    text = f"{failure.get('message', '')}\n{failure.get('traceback', '')}"
    if nodeid in _SYNTHETIC_ENVIRONMENT or error_type in _ENVIRONMENT:
        return "environment"
    if error_type in _SYNTAX or (profile.name == "javascript" and _JS_SYNTAX.search(text)):
        return "syntax"
    if error_type in _IMPORT or (profile.name == "javascript" and _JS_IMPORT.search(text)):
        return "import"
    paths = _PATHS.findall(str(failure.get("traceback", "")))
    if (
        paths
        and error_type not in ("AssertionError", "Unknown", "")
        and all(_is_test_path(p, profile) for p in paths)
    ):
        return "test_wrong"  # the error never reaches implementation code
    return "logic"


# Fix the most basic problem first: a file that does not parse hides everything else.
_PRIORITY: tuple[FailureClass, ...] = ("syntax", "import", "environment", "test_wrong", "logic")


def classify_failure(
    failures: list[dict[str, Any]], profile: LanguageProfile = PYTHON
) -> FailureClass:
    """Class of the most fundamental failure present (`logic` when there are none)."""
    found = {_one(f, profile) for f in failures}
    for cls in _PRIORITY:
        if cls in found:
            return cls
    return "logic"
