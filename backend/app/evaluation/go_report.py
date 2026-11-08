"""Go support for the Verifier and quality checks (Phase 16, ADR-0023).

`go test -json` prints one JSON event per line on stdout; these helpers normalise that stream and
the statement coverage profile into the same shapes the pytest and Jest paths produce.
"""

import json
import re
from pathlib import Path
from typing import Any

MAX_TRACE_CHARS = 6000
_VET_LINE = re.compile(r"^(?P<file>[^\s:]+\.go):(?P<line>\d+)(?::\d+)?:\s*(?P<msg>.+)$")
_BUILD_FAILED = re.compile(
    r"\[build failed\]|build failed|cannot find package|undefined:|syntax error|\.go:\d+:\d+:",
    re.I,
)


def parse_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and "Action" in obj:
            events.append(obj)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and failure records from test events. Only events that name a Test are tests."""
    outcome: dict[str, str] = {}
    output: dict[str, list[str]] = {}
    package_output: dict[str, list[str]] = {}
    package_failed: set[str] = set()
    for ev in events:
        action, test, pkg = ev.get("Action"), ev.get("Test"), str(ev.get("Package", ""))
        key = f"{pkg}::{test}" if test else ""
        if action == "output":
            text = str(ev.get("Output", ""))
            (output.setdefault(key, []) if test else package_output.setdefault(pkg, [])).append(
                text
            )
        elif action in ("pass", "fail", "skip"):
            if test:
                outcome[key] = str(action)
            elif action == "fail":
                package_failed.add(pkg)
    passed = sum(1 for v in outcome.values() if v == "pass")
    failed_keys = [k for k, v in outcome.items() if v == "fail"]
    skipped = sum(1 for v in outcome.values() if v == "skip")
    failures: list[dict[str, str]] = []
    for key in failed_keys:
        text = "".join(output.get(key, []))
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("===")]
        message = next((ln for ln in lines if not ln.startswith("--- ")), lines[0] if lines else "")
        failures.append(
            {"nodeid": key, "message": message[:300], "traceback": text[-MAX_TRACE_CHARS:]}
        )
    # A package that failed without any failing test did not compile (or panicked at init).
    leaf_failed = {k.split("::", 1)[0] for k in failed_keys}
    for pkg in sorted(package_failed - leaf_failed):
        text = "".join(package_output.get(pkg, []))
        failures.append(
            {
                "nodeid": f"{pkg}::<build>" if _BUILD_FAILED.search(text) else f"{pkg}::<package>",
                "message": (text.strip().splitlines() or ["package failed"])[0][:300],
                "traceback": text[-MAX_TRACE_CHARS:],
            }
        )
    return {
        "total": len(outcome),
        "passed": passed,
        "failed": len(failed_keys),
        "skipped": skipped,
        "failures": failures,
        "found": bool(events),
    }


def parse_coverprofile(path: Path) -> float | None:
    """Statement coverage percent from a Go cover profile (a header, then one line per block)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    total = covered = 0
    for line in text.splitlines()[1:]:
        parts = line.rsplit(" ", 2)
        if len(parts) != 3:
            continue
        try:
            statements, count = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        total += statements
        covered += statements if count > 0 else 0
    return round(100.0 * covered / total, 2) if total else None


def parse_vet(stderr: str) -> list[dict[str, Any]]:
    """`go vet` reports `file.go:line:col: message` on stderr; a finding per such line."""
    items: list[dict[str, Any]] = []
    for line in stderr.splitlines():
        m = _VET_LINE.match(line.strip())
        if m:
            items.append(
                {
                    "filename": m["file"],
                    "line": int(m["line"]),
                    "code": "vet",
                    "message": m["msg"][:300],
                }
            )
    return items[:25]


# ---- source scanning used by the test guard and the repo map -------------------------------

_TEST_FUNC = re.compile(r"^func\s+(Test\w*)\s*\(", re.M)
_ASSERT = re.compile(
    r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\bassert\.\w+\(|\brequire\.\w+\("
)
_SKIP = re.compile(r"\bt\.Skip(?:f|Now)?\s*\(")
_SYMBOL = re.compile(
    r"^(?:func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)|type\s+([A-Za-z_]\w*)\s+(?:struct|interface))",
    re.M,
)
_IMPORT_BLOCK = re.compile(r"^import\s*\((.*?)\)", re.M | re.S)


def test_stats(source: str) -> tuple[int, int, int]:
    return len(_TEST_FUNC.findall(source)), len(_ASSERT.findall(source)), len(_SKIP.findall(source))


def symbols(source: str) -> list[str]:
    return [next(g for g in m.groups() if g) for m in _SYMBOL.finditer(source)][:40]


def module_name(go_mod: str) -> str:
    m = re.search(r"^module\s+(\S+)", go_mod, re.M)
    return m.group(1) if m else ""
