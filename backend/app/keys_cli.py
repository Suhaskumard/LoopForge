"""Operator command for the key ring (Phase 17). Talks to the database directly (run it where the
worker/API run); it never prints key material or secret values.

    python -m app.keys_cli status
    python -m app.keys_cli rotate --dry-run
    python -m app.keys_cli rotate

Exit codes: 0 ok, 1 some values could not be decrypted (their key is missing from the ring).
"""

import argparse
import json
import sys
from collections.abc import Sequence

from app.database.session import SessionLocal
from app.services import key_rotation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loopforge-keys")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="how many stored values are encrypted under which key")
    rot = sub.add_parser("rotate", help="re-encrypt every stored secret under the active key")
    rot.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        if args.command == "status":
            print(json.dumps(key_rotation.status(db), sort_keys=True))
            return 0
        report = key_rotation.rotate(db, dry_run=args.dry_run)
    print(
        json.dumps(
            {
                "active": report.active,
                "dry_run": report.dry_run,
                "rotated": report.rotated,
                "already_current": report.already_current,
                "failed": report.failed,
            },
            sort_keys=True,
        )
    )
    return 1 if report.failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
