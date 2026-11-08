"""Write the live OpenAPI document to docs/openapi.json (Phase 18).

    python scripts/export_openapi.py            # regenerate the snapshot (a deliberate act: review the diff)
    python scripts/export_openapi.py --check    # exit 1 if the snapshot is stale (the gate and a test use this)

The snapshot is what the SDKs and the docs are written against; `test_phase18_platform.py` also fails when the
live schema drifts from it, so an API change can never slip in unnoticed.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402

TARGET = ROOT / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print("docs/openapi.json is stale: run `python scripts/export_openapi.py` and review the diff")
            return 1
        print("docs/openapi.json is current")
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)} ({len(json.loads(text)['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
