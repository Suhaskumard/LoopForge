"""Language profiles (Phase 8, ADR-0015): everything that differs between languages.

The Verifier, quality checks and command runner ask a `LanguageProfile` how to run tests, lint and
check dependencies instead of assuming Python. A profile only describes *what* to run; the sandbox
still decides *how* (no network, resource caps - ADR-0008).
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings

PY_SOURCE_EXT = frozenset({".py"})
JS_SOURCE_EXT = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})
_TEST_NAME = {
    "python": re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$|(^|/)tests/[^/]*\.py$"),
    "javascript": re.compile(r"(\.|/)(test|spec)\.(m|c)?[jt]sx?$|(^|/)__tests__/"),
}
_TEST_DECL = {
    "python": re.compile(r"^\s*(?:async\s+)?def\s+test_\w+", re.M),
    "javascript": re.compile(r"^\s*(?:it|test)(?:\.\w+)?\s*\(", re.M),
}
JS_APPROVED_FILE = (
    Path(__file__).resolve().parents[2] / "sandbox" / "node" / "approved_packages_js.txt"
)


@dataclass(frozen=True)
class LanguageProfile:
    name: str
    source_extensions: frozenset[str]
    manifest: str  # dependency manifest in the workspace root
    image_setting: str  # name of the Settings attribute holding the sandbox image
    test_argv: tuple[str, ...]
    report_name: str
    coverage_name: str
    lint_argv: tuple[str, ...]
    framework_label: str  # used in prompts
    test_command_label: str

    @property
    def image(self) -> str:
        return str(getattr(settings, self.image_setting))

    def is_test_file(self, path: str) -> bool:
        return bool(_TEST_NAME[self.name].search(path))

    def count_tests(self, files: dict[str, str]) -> int:
        """Static lower-bound count of test declarations (anti-test-deletion baseline)."""
        pattern = _TEST_DECL[self.name]
        return sum(len(pattern.findall(t)) for p, t in files.items() if self.is_test_file(p))

    def check_dependencies(self, manifest_text: str) -> list[str]:
        return _CHECKERS[self.name](manifest_text)


def _py_deps(text: str) -> list[str]:
    from app.execution.dependencies import check_requirements

    return check_requirements(text)


def load_approved_js(path: Path = JS_APPROVED_FILE) -> dict[str, str]:
    approved: dict[str, str] = {}
    if not path.is_file():
        return approved
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            approved[name.strip()] = version.strip()
    return approved


def _js_deps(text: str, approved: dict[str, str] | None = None) -> list[str]:
    approved = approved if approved is not None else load_approved_js()
    try:
        data = json.loads(text)
    except ValueError:
        return ["package.json is not valid JSON"]
    if not isinstance(data, dict):
        return ["package.json must be an object"]
    violations: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(section) or {}
        if not isinstance(deps, dict):
            violations.append(f"{section} must be an object")
            continue
        for name, version in deps.items():
            if name not in approved:
                violations.append(f"package not approved: {name}")
            elif str(version).lstrip("^~=") != approved[name]:
                violations.append(f"{name}@{version} is not the approved version {approved[name]}")
    scripts = data.get("scripts") or {}
    for hook in ("preinstall", "install", "postinstall", "prepare"):
        if isinstance(scripts, dict) and hook in scripts:
            violations.append(f"install-time script not allowed: {hook}")
    return violations


_CHECKERS: dict[str, Callable[[str], list[str]]] = {"python": _py_deps, "javascript": _js_deps}

PYTHON = LanguageProfile(
    name="python",
    source_extensions=PY_SOURCE_EXT,
    manifest="requirements.txt",
    image_setting="sandbox_image",
    test_argv=(
        "python",
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        "--json-report",
        "--json-report-file=/out/report.json",
        "--rootdir=/workspace",
        "--cov=/workspace",
        "--cov-report=json:/out/coverage.json",
    ),  # fmt: skip
    report_name="report.json",
    coverage_name="coverage.json",
    lint_argv=("ruff", "check", "--output-format=json", "--no-cache", "/workspace"),
    framework_label="Python FastAPI application (pytest)",
    test_command_label="pytest",
)

JAVASCRIPT = LanguageProfile(
    name="javascript",
    source_extensions=JS_SOURCE_EXT,
    manifest="package.json",
    image_setting="sandbox_image_js",
    test_argv=(
        "jest",
        "--ci",
        "--json",
        "--outputFile=/out/report.json",
        "--rootDir=/workspace",
        "--no-cache",
        "--coverage",
        "--coverageReporters=json-summary",
        "--coverageDirectory=/out/coverage",
    ),  # fmt: skip
    report_name="report.json",
    coverage_name="coverage/coverage-summary.json",
    lint_argv=("eslint", "--format=json", "--no-warn-ignored", "/workspace"),
    framework_label="Node.js / TypeScript project (Jest)",
    test_command_label="jest",
)

PROFILES: dict[str, LanguageProfile] = {"python": PYTHON, "javascript": JAVASCRIPT}
SUPPORTED = tuple(PROFILES)
_ALIASES = {"typescript": "javascript", "js": "javascript", "ts": "javascript", "py": "python"}


def get_profile(name: str | None) -> LanguageProfile:
    key = (name or "python").lower()
    key = _ALIASES.get(key, key)
    if key not in PROFILES:
        raise ValueError(f"unsupported language: {name!r} (supported: {', '.join(SUPPORTED)})")
    return PROFILES[key]


def image_for_argv(argv: list[str]) -> str:
    """Sandbox image for an (already allowlisted) command: JS tools run in the Node image."""
    return JAVASCRIPT.image if argv and argv[0] in ("jest", "eslint") else PYTHON.image


def detect_language(files: dict[str, str]) -> str:
    """Pick the profile for an imported repository from its manifest / source mix."""
    if "package.json" in files and "requirements.txt" not in files:
        return "javascript"
    py = sum(1 for p in files if p.endswith(".py"))
    js = sum(1 for p in files if Path(p).suffix in JS_SOURCE_EXT)
    return "javascript" if js > py else "python"


# ---- Jest report parsing (normalised into the same shapes as pytest) -----------------------


def jest_counts(data: dict[str, Any]) -> dict[str, int]:
    return {
        "passed": int(data.get("numPassedTests", 0)),
        "failed": int(data.get("numFailedTests", 0)),
        "skipped": int(data.get("numPendingTests", 0)) + int(data.get("numTodoTests", 0)),
        "total": int(data.get("numTotalTests", 0)),
    }
