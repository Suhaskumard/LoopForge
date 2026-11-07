"""Controlled dependency policy (Addendum §19.2, minimal Phase 3 form).

The sandbox has no network and cannot install anything. Dependencies are baked into the image
from `sandbox/approved_packages.txt`; a generated project may only use packages that are approved
AND pinned to the approved version. Anything else fails the run before execution.
"""

import re
from pathlib import Path

APPROVED_FILE = Path(__file__).resolve().parents[2] / "sandbox" / "approved_packages.txt"
_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:==\s*([A-Za-z0-9.+!_-]+))?\s*$")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_approved(path: Path = APPROVED_FILE) -> dict[str, str]:
    approved: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(raw.strip())
        if m and m.group(2):
            approved[_norm(m.group(1))] = m.group(2)
    return approved


def check_requirements(text: str, approved: dict[str, str] | None = None) -> list[str]:
    """Return policy violations for a requirements.txt body (empty list = compliant)."""
    approved = approved if approved is not None else load_approved()
    violations: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _LINE.match(line.replace("[standard]", ""))
        if not m:
            violations.append(f"unsupported requirement line: {line!r}")
            continue
        name, version = _norm(m.group(1)), m.group(2)
        if name not in approved:
            violations.append(f"package not approved: {name}")
        elif version is None:
            violations.append(f"package must be pinned with ==: {name}")
        elif version != approved[name]:
            violations.append(f"{name}=={version} is not the approved version {approved[name]}")
    return violations
