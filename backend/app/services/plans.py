"""Plans: named bundles of org-level quotas (Phase 18).

``PLANS_JSON={"free": {"token_quota_month": 100000, "max_tasks_month": 20}, "team": {...}}``. An
organization's own explicit quota (set by its admin or the operator) always wins; the plan
supplies the
default where the org has none. ``Organization.plan`` is assigned by the platform operator
(``python -m app.ops_cli set-plan``), never by the organization's own admins - otherwise a plan
would
not limit anything. Billing is out of scope: a plan is a set of limits, not a payment relationship.
"""

import json
from typing import Any

from app.config import settings
from app.database.models import Organization

KEYS = ("token_quota_month", "max_tasks_month")


def validate(raw: str) -> None:
    """Raise ValueError for malformed PLANS_JSON (called at startup)."""
    if not raw.strip():
        return
    try:
        data = json.loads(raw)
        ok = isinstance(data, dict) and all(
            isinstance(name, str)
            and isinstance(caps, dict)
            and set(caps) <= set(KEYS)
            and all(
                v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0)
                for v in caps.values()
            )
            for name, caps in data.items()
        )
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(
            'PLANS_JSON must be {"<plan>": {"token_quota_month": <int>, "max_tasks_month": <int>}}'
        )


def all_plans() -> dict[str, dict[str, Any]]:
    return json.loads(settings.plans_json) if settings.plans_json.strip() else {}


def token_quota(org: Organization) -> int | None:
    if org.token_quota_month is not None:
        return org.token_quota_month
    value = all_plans().get(org.plan, {}).get("token_quota_month")
    return int(value) if value is not None else None


def max_tasks(org: Organization) -> int | None:
    if org.max_tasks_month is not None:
        return org.max_tasks_month
    value = all_plans().get(org.plan, {}).get("max_tasks_month")
    return int(value) if value is not None else None
