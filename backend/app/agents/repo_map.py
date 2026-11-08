"""Repo understanding (Phase 8): a deterministic map of the seeded repository for the Planner.

No LLM and no execution: files are only read as text (Python is parsed with `ast`, which never
runs code). The map is bounded so a large repository cannot flood the prompt, and it is wrapped as
untrusted input by the caller because file names and symbols come from the repository.
"""

import ast
import json
import re
from typing import Any

from app.evaluation import go_report
from app.execution.languages import LanguageProfile

MAX_TREE = 300
MAX_SYMBOL_FILES = 60
MAX_SYMBOLS_PER_FILE = 20
_JS_SYMBOL = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)|"
    r"class\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()",
    re.M,
)


def _py_symbols(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return ["<unparseable>"]
    out = [
        f"{'class' if isinstance(n, ast.ClassDef) else 'def'} {n.name}"
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return out[:MAX_SYMBOLS_PER_FILE]


def _js_symbols(text: str) -> list[str]:
    names = [next(g for g in m.groups() if g) for m in _JS_SYMBOL.finditer(text)]
    return names[:MAX_SYMBOLS_PER_FILE]


def symbols_for(profile: LanguageProfile, text: str) -> list[str]:
    if profile.name == "python":
        return _py_symbols(text)
    if profile.name == "go":
        return go_report.symbols(text)
    return _js_symbols(text)


def _entry_points(profile: LanguageProfile, files: dict[str, str]) -> list[str]:
    found: list[str] = []
    if profile.name == "python":
        for path, text in files.items():
            if path.endswith(("main.py", "app.py", "__main__.py", "manage.py")) or (
                path.endswith(".py") and "__main__" in text and "if __name__" in text
            ):
                found.append(path)
    elif profile.name == "go":
        for path, text in files.items():
            if path.endswith(".go") and not path.endswith("_test.go") and "func main(" in text:
                found.append(path)
    else:
        try:
            pkg = json.loads(files.get("package.json", "{}"))
            if isinstance(pkg, dict):
                if isinstance(pkg.get("main"), str):
                    found.append(pkg["main"])
                found += [f"npm script: {k}" for k in (pkg.get("scripts") or {})][:10]
        except ValueError:
            pass
    return found[:15]


def build_repo_map(files: dict[str, str], profile: LanguageProfile) -> dict[str, Any]:
    paths = sorted(files)
    source = [p for p in paths if any(p.endswith(e) for e in profile.source_extensions)]
    symbols: dict[str, list[str]] = {}
    for path in source[:MAX_SYMBOL_FILES]:
        syms = symbols_for(profile, files[path])
        if syms:
            symbols[path] = syms
    return {
        "language": profile.name,
        "file_count": len(paths),
        "files": paths[:MAX_TREE],
        "files_truncated": len(paths) > MAX_TREE,
        "entry_points": _entry_points(profile, files),
        "test_files": [p for p in paths if profile.is_test_file(p)][:100],
        "test_command": profile.test_command_label,
        "manifest": profile.manifest if profile.manifest in files else None,
        "symbols": symbols,
    }
