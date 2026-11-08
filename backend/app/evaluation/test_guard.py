"""Test-quality guard (Phase 9, ADR-0016): a repair may not make the test suite weaker.

The Decision Engine already refuses a *smaller* suite. This catches the quieter ways to "pass":
removing assertions, skipping or xfail-ing tests, or deleting a test while adding another. It
compares a test file before and after a repair; any finding rejects the patch (`repair._validator`).
"""

import ast
import re

from app.execution.languages import PYTHON, LanguageProfile

_JS_TEST = re.compile(r"^\s*(?:it|test)\s*\(", re.M)
_JS_ASSERT = re.compile(r"\bexpect\s*\(|\bassert\w*\s*\(")
_JS_SKIP = re.compile(r"\.skip\b|\.todo\b|\bx(?:it|test|describe)\s*\(")
_PY_SKIP = re.compile(r"\b(skip|skipif|xfail)\b")


def _py_stats(source: str) -> tuple[set[str], int, int] | None:
    """(test function names, assertion count, skip/xfail markers), or None if it does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    names: set[str] = set()
    asserts = skips = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                names.add(node.name)
            skips += sum(1 for d in node.decorator_list if _PY_SKIP.search(ast.unparse(d)))
        elif isinstance(node, ast.Assert):
            asserts += 1
        elif isinstance(node, ast.Call):
            callee = ast.unparse(node.func)
            if re.search(r"\bpytest\.(skip|xfail)$", callee):
                skips += 1
            elif re.search(r"\.raises$|\.warns$|\bassert\w*$", callee):
                asserts += 1  # pytest.raises / self.assertX are assertions too
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            skips += 1 if _PY_SKIP.search(ast.unparse(node.value)) else 0
    return names, asserts, skips


def _js_stats(source: str) -> tuple[int, int, int]:
    return (
        len(_JS_TEST.findall(source)),
        len(_JS_ASSERT.findall(source)),
        len(_JS_SKIP.findall(source)),
    )


def detect_test_weakening(
    old_files: dict[str, str],
    new_files: dict[str, str],
    profile: LanguageProfile = PYTHON,
) -> list[str]:
    """Human-readable findings; an empty list means the test files did not get weaker."""
    findings: list[str] = []
    for path, old in old_files.items():
        if not profile.is_test_file(path) or path not in new_files or new_files[path] == old:
            continue
        new = new_files[path]
        if profile.name == "python":
            before, after = _py_stats(old), _py_stats(new)
            if before is None:
                continue  # it was already broken; nothing to protect
            if after is None:
                findings.append(f"{path}: the edited test file no longer parses")
                continue
            removed = before[0] - after[0]
            if removed:
                findings.append(f"{path}: removed test(s) {sorted(removed)}")
            if after[1] < before[1]:
                findings.append(f"{path}: assertions reduced from {before[1]} to {after[1]}")
            if after[2] > before[2]:
                findings.append(f"{path}: adds skip/xfail markers")
        else:
            b_tests, b_asserts, b_skips = _js_stats(old)
            a_tests, a_asserts, a_skips = _js_stats(new)
            if a_tests < b_tests:
                findings.append(f"{path}: tests reduced from {b_tests} to {a_tests}")
            if a_asserts < b_asserts:
                findings.append(f"{path}: assertions reduced from {b_asserts} to {a_asserts}")
            if a_skips > b_skips:
                findings.append(f"{path}: adds skip/todo markers")
    return findings
