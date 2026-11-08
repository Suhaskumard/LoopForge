"""Targeted Repair context (Phase 9, ADR-0016): send the files that matter, outline the rest.

Before: every file up to a size cap, files named in the failure first. Now: files named in the
failure report, plus the files they import directly (one hop), are sent in full; every other file
is reduced to its path and symbols (`repo_map` extractors). If the failure names no file at all,
nothing is hidden (the old behaviour), because guessing would be worse than sending everything.
"""

import ast
import posixpath
import re

from app.agents.repo_map import MAX_SYMBOLS_PER_FILE, symbols_for
from app.execution.languages import LanguageProfile

_JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""")
_JS_EXT = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")


def _named_files(files: dict[str, str], failure_text: str) -> set[str]:
    text = failure_text.replace("\\\\", "/").replace("\\", "/")
    return {p for p in files if p in text}


def _py_imports(path: str, source: str, files: dict[str, str]) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative import: resolve against the importing file's package
                pkg = posixpath.dirname(path).split("/") if posixpath.dirname(path) else []
                pkg = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = ".".join([*pkg, base] if base else pkg)
            mods.add(base)
            mods.update(f"{base}.{a.name}" if base else a.name for a in node.names)
    found: set[str] = set()
    for mod in mods:
        stem = mod.replace(".", "/")
        for cand in (f"{stem}.py", f"{stem}/__init__.py"):
            if cand in files:
                found.add(cand)
    return found


def _js_imports(path: str, source: str, files: dict[str, str]) -> set[str]:
    found: set[str] = set()
    for rel in _JS_IMPORT.findall(source):
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), rel))
        for cand in (
            target,
            *(target + ext for ext in _JS_EXT),
            *(f"{target}/index{e}" for e in _JS_EXT),
        ):
            if cand in files:
                found.add(cand)
                break
    return found


def _go_imports(path: str, source: str, files: dict[str, str]) -> set[str]:
    """A Go package is a directory: its other files are what a file depends on."""
    here = posixpath.dirname(path)
    return {p for p in files if p != path and p.endswith(".go") and posixpath.dirname(p) == here}


_IMPORT_FINDERS = {"python": _py_imports, "javascript": _js_imports, "go": _go_imports}


def _outline(path: str, text: str, profile: LanguageProfile) -> str:
    if posixpath.splitext(path)[1] not in profile.source_extensions:
        shown = "(not a source file)"  # manifests, configs: nothing to extract
    else:
        symbols = symbols_for(profile, text)
        shown = ", ".join(symbols[:MAX_SYMBOLS_PER_FILE]) or "(no top-level symbols)"
    return f"--- {path} (outline only: {len(text)} chars; symbols: {shown})"


def select_context(
    files: dict[str, str], failure_text: str, profile: LanguageProfile, *, max_chars: int
) -> str:
    """Prompt text for the Repair agent: full text of relevant files, outlines of the rest."""
    named = _named_files(files, failure_text)
    if not named:
        full = set(files)  # no signal: keep the old send-everything behaviour
    else:
        full = set(named)
        for path in sorted(named):
            finder = _IMPORT_FINDERS.get(profile.name, _js_imports)
            full |= finder(path, files[path], files)
    parts, total = [], 0
    for rel in sorted(files, key=lambda p: (p not in named, p not in full, p)):
        text = files[rel]
        if rel not in full:
            parts.append(_outline(rel, text, profile))
        elif total + len(text) > max_chars:
            parts.append(f"--- {rel} (omitted: size limit)")
        else:
            total += len(text)
            parts.append(f"--- {rel}\n{text}")
    return "\n".join(parts)
