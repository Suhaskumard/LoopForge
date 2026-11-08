"""Mutation-style check of the generated tests (Phase 16, `test_mutation_check`).

Small deliberate changes ("mutants") are made to the code under test in a scratch copy; if the
tests still pass, they would not notice that behaviour changed. Python only. A bounded sample, not
a full mutation run, and report-only: it never changes a verdict.
"""

import ast
import copy
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.test_runner import run_tests
from app.execution.languages import PYTHON, LanguageProfile
from app.execution.sandbox import Sandbox
from app.services import workspace

_SWAPS: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
}  # fmt: skip
_ARITH: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv,
}  # fmt: skip


@dataclass(frozen=True)
class Mutant:
    path: str
    line: int
    description: str
    source: str


def _candidates(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    found: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _SWAPS:
            found.append((node, "flip comparison"))
        elif isinstance(node, ast.BinOp) and type(node.op) in _ARITH:
            found.append((node, "swap arithmetic operator"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            found.append((node, "negate boolean literal"))
        elif isinstance(node, ast.Return) and node.value is not None:
            found.append((node, "return None"))
    return found


def _apply(node: ast.AST) -> None:
    if isinstance(node, ast.Compare):
        node.ops = [_SWAPS[type(node.ops[0])]()]
    elif isinstance(node, ast.BinOp):
        node.op = _ARITH[type(node.op)]()
    elif isinstance(node, ast.Constant):
        node.value = not node.value
    elif isinstance(node, ast.Return):
        node.value = ast.Constant(value=None)


def mutants_of(path: str, source: str, limit: int) -> list[Mutant]:
    """Up to `limit` single-change mutants of one file, spread across the file."""
    try:
        base = ast.parse(source)
    except SyntaxError:
        return []
    total = len(_candidates(base))
    if total == 0 or limit <= 0:
        return []
    step = max(1, total // limit)
    out: list[Mutant] = []
    for idx in range(0, total, step)[:limit]:
        tree = copy.deepcopy(base)
        node, why = _candidates(tree)[idx]
        line = getattr(node, "lineno", 0)
        _apply(node)
        ast.fix_missing_locations(tree)
        out.append(Mutant(path, line, why, ast.unparse(tree)))
    return out


def run_mutation_check(
    sandbox: Sandbox,
    src: Path,
    out_dir: Path,
    changed_sources: list[str],
    timeout: int,
    *,
    max_mutants: int = 6,
    budget_seconds: float = 120.0,
    profile: LanguageProfile = PYTHON,
) -> dict[str, Any]:
    """Run the suite against each mutant. `killed` = the suite noticed (it no longer passes)."""
    per_file = max(1, max_mutants // max(1, len(changed_sources)))
    pending: list[Mutant] = []
    for rel in changed_sources:
        target = src / rel
        if target.is_file():
            pending += mutants_of(rel, target.read_text(encoding="utf-8"), per_file)
    pending = pending[:max_mutants]
    started, results = time.monotonic(), []
    scratch_root = workspace.workspace_root()
    scratch_root.mkdir(parents=True, exist_ok=True)
    for m in pending:
        if time.monotonic() - started > budget_seconds:
            break
        scratch = Path(tempfile.mkdtemp(prefix=".mutant-", dir=scratch_root))
        try:
            shutil.copytree(src, scratch, dirs_exist_ok=True)
            (scratch / m.path).write_text(m.source, encoding="utf-8")
            summary, _ = run_tests(sandbox, scratch, out_dir, timeout, profile)
            results.append((m, not summary.ok))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    killed = sum(1 for _, k in results if k)
    return {
        "tried": len(results),
        "killed": killed,
        "score": round(killed / len(results), 4) if results else None,
        "survivors": [
            {"path": m.path, "line": m.line, "change": m.description} for m, k in results if not k
        ][:10],
    }
