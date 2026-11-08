"""Platform-operator commands (Phase 18). Talks to the database directly, not over HTTP:
assigning a plan is the operator's decision, not something an organization's own admins may do.

    python -m app.ops_cli plans                       # configured plans and how many orgs use each
    python -m app.ops_cli set-plan <org-slug> <plan>  # assign (the plan must exist in PLANS_JSON)
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence

from sqlalchemy import select

from app.database.models import Organization
from app.database.session import SessionLocal
from app.services import audit_service, plans


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loopforge-ops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plans", help="list configured plans and their usage")
    sp = sub.add_parser("set-plan", help="assign a plan to an organization")
    sp.add_argument("org_slug")
    sp.add_argument("plan")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        if args.command == "plans":
            used = Counter(o.plan for o in db.scalars(select(Organization)))
            print(
                json.dumps(
                    {"plans": plans.all_plans(), "organizations_per_plan": used}, sort_keys=True
                )
            )
            return 0
        known = plans.all_plans()
        if args.plan != "default" and args.plan not in known:
            print(
                f"error: unknown plan '{args.plan}' (configured: {sorted(known)})", file=sys.stderr
            )
            return 2
        org = db.scalars(select(Organization).where(Organization.slug == args.org_slug)).first()
        if org is None:
            print(f"error: no organization with slug '{args.org_slug}'", file=sys.stderr)
            return 2
        before, org.plan = org.plan, args.plan
        db.commit()
        audit_service.record(
            db, org_id=org.id, actor_id=None, action="org.plan_changed", target_type="org",
            target_id=org.id, detail={"from": before, "to": args.plan},
        )  # fmt: skip
        print(f"{org.slug}: {before} -> {args.plan}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
