"""Upgrade test (Phase 18): data written under the PREVIOUS schema survives the upgrade to head.

    python scripts/upgrade_test.py                                  # SQLite, a throwaway file
    python scripts/upgrade_test.py --database-url postgresql+psycopg://...   # an EMPTY database you own

What it does (the previous release's schema head comes from docs/schema_baselines.json):
 1. migrate an empty database to the previous head and fill it with realistic data using the OLD columns:
    users with a bcrypt password, an organization with members, a project and tasks, audit rows, a stored GitHub
    token encrypted the pre-key-ring way, a webhook with a plaintext signing secret;
 2. note a login token signed the pre-key-ring way (no `kid`);
 3. `alembic upgrade head`;
 4. in a fresh process with the NEW code: every row is still there, the old password and old token still work,
    the old encrypted token decrypts, the old webhook secret still signs, new columns have safe defaults, and the
    append-only audit triggers are alive;
 5. (SQLite) roll back to the previous head and forward again: the core data is unchanged.
A failure of any check exits 1. This proves the migration path from ONE specific earlier schema, with the data
shapes seeded here - not every possible production database.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PYTHON = sys.executable
BASELINES = json.loads((ROOT / "docs" / "schema_baselines.json").read_text(encoding="utf-8"))
PREVIOUS = BASELINES["previous_release"]["head"]
CURRENT = BASELINES["current"]["head"]
JWT_SECRET = "upgrade-test-secret-0123456789abcdef-0123"  # the (old) signing key the seed used
PASSWORD = "correct horse battery"


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url, "JWT_SECRET": JWT_SECRET}
    r = subprocess.run([PYTHON, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FAIL: alembic {' '.join(args)}\n{r.stdout}\n{r.stderr}")


def _dummy(col) -> object:
    from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, Uuid

    t = col.type
    if isinstance(t, Boolean):
        return False
    if isinstance(t, Integer):
        return 0
    if isinstance(t, Float):
        return 0.0
    if isinstance(t, DateTime):
        return datetime(2026, 1, 1)
    if isinstance(t, Uuid):
        return uuid.uuid4()
    if isinstance(t, JSON):
        return {}
    if isinstance(t, (String, Text)):
        return "x"
    return "x"


def insert(conn, table: str, **given) -> None:
    """INSERT using the database's CURRENT (old) columns: anything required but not given gets a dummy."""
    import sqlalchemy as sa

    meta = sa.MetaData()
    tbl = sa.Table(table, meta, autoload_with=conn)
    values = dict(given)
    for col in tbl.columns:
        if col.name in values or col.nullable or col.server_default is not None:
            continue
        values[col.name] = _dummy(col)
    native = conn.dialect.name != "sqlite"  # the app stores UUIDs as 32-char hex on SQLite
    for k, v in values.items():
        if isinstance(v, uuid.UUID):
            values[k] = str(v) if native else v.hex
    conn.execute(sa.insert(tbl).values(**values))


def seed(url: str) -> dict:
    import bcrypt
    import jwt
    import sqlalchemy as sa
    from cryptography.fernet import Fernet

    engine = sa.create_engine(url)
    user_id, org_id, project_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 5, 1, 12, 0, 0)
    key = base64.urlsafe_b64encode(hashlib.sha256(JWT_SECRET.encode()).digest())  # pre-key-ring: JWT_SECRET
    with engine.begin() as c:
        insert(c, "users", id=user_id, email="legacy@example.com", token_version=0, created_at=now,
               password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode())  # fmt: skip
        insert(c, "organizations", id=org_id, name="Legacy Org", slug="legacy-org", created_at=now)
        insert(c, "memberships", id=uuid.uuid4(), org_id=org_id, user_id=user_id, role="admin", created_at=now)
        insert(c, "projects", id=project_id, user_id=user_id, org_id=org_id, name="old project", created_at=now)
        for i in range(3):
            insert(c, "tasks", id=uuid.uuid4(), project_id=project_id, requirement=f"Build thing {i} please",
                   status="COMPLETED", max_iterations=5, current_iteration=1, version=1, created_at=now)  # fmt: skip
        for i in range(5):
            insert(c, "audit_log", id=uuid.uuid4(), org_id=org_id, actor_id=user_id, action=f"seed.{i}",
                   target_type="seed", target_id=str(i), detail={"n": i}, ip="", created_at=now)  # fmt: skip
        insert(c, "org_integrations", id=uuid.uuid4(), org_id=org_id, provider="github", created_at=now,
               token_enc=Fernet(key).encrypt(b"ghp_legacy_token").decode())  # fmt: skip
        insert(c, "webhook_endpoints", id=uuid.uuid4(), org_id=org_id, url="https://hooks.example.com/in",
               secret="whsec_legacy_plain", events=[], format="json", active=True, created_at=now)  # fmt: skip
    old_jwt = jwt.encode(
        {"sub": str(user_id), "tv": 0, "exp": int(time.time()) + 3600}, JWT_SECRET, algorithm="HS256"
    )  # no `kid` header: how every pre-Phase-17 token looked
    counts = counts_of(engine)
    engine.dispose()
    return {"user_id": str(user_id), "org_id": str(org_id), "old_jwt": old_jwt, "counts": counts}


CORE = ("users", "organizations", "memberships", "projects", "tasks", "audit_log", "org_integrations", "webhook_endpoints")


def counts_of(engine) -> dict[str, int]:
    import sqlalchemy as sa

    with engine.connect() as c:
        return {t: c.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() for t in CORE}  # noqa: S608


CHECKS = r'''
import json, sys, time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.config import settings
from app.main import app
from app.services import publish_service
from app.services.webhook_service import signature_header
from app.database.models import WebhookEndpoint
from sqlalchemy.orm import Session

seed = json.loads(sys.argv[1])
results = {}
client = TestClient(app)
engine = create_engine(settings.database_url)

me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + seed["old_jwt"]})
results["old_token_without_kid_still_verifies"] = me.status_code == 200 and me.json()["email"] == "legacy@example.com"
login = client.post("/api/v1/auth/login", data={"username": "legacy@example.com", "password": seed["password"]})
results["old_password_still_logs_in"] = login.status_code == 200
new_token = login.json().get("access_token", "")
orgs = client.get("/api/v1/orgs", headers={"Authorization": "Bearer " + new_token}).json() if new_token else []
results["org_and_role_intact"] = [(o["slug"], o["role"]) for o in orgs] == [("legacy-org", "admin")]
results["new_org_defaults"] = bool(orgs) and client.get(f"/api/v1/orgs/{orgs[0]['id']}", headers={"Authorization": "Bearer " + new_token}).json().get("plan") == "default"

with Session(engine) as db:
    import uuid
    tok = publish_service._token(db, uuid.UUID(seed["org_id"]))
    results["legacy_encrypted_token_still_decrypts"] = tok == "ghp_legacy_token"
    ep = db.query(WebhookEndpoint).one()
    header = signature_header(ep, b"{}")
    from app.services.webhook_service import verify_signature
    results["legacy_plaintext_webhook_secret_still_signs"] = verify_signature("whsec_legacy_plain", b"{}", header)

with engine.connect() as c:
    results["users_active_defaults_true"] = c.execute(text("select min(case when active then 1 else 0 end) from users")).scalar_one() == 1
    results["membership_source_defaults_manual"] = c.execute(text("select count(*) from memberships where source <> 'manual'")).scalar_one() == 0
    results["org_require_mfa_defaults_false"] = c.execute(text("select count(*) from organizations where require_mfa")).scalar_one() == 0
    for table in ("rate_counters", "idempotency_keys", "scim_tokens", "scim_identities"):
        results[f"new_table_{table}"] = c.execute(text(f"select count(*) from {table}")).scalar_one() == 0

try:
    with engine.begin() as c:
        c.execute(text("delete from audit_log"))
    results["audit_log_still_append_only"] = False
except Exception:
    results["audit_log_still_append_only"] = True
print(json.dumps(results))
'''


def verify_new_code(url: str, seeded: dict) -> dict[str, bool]:
    env = {**os.environ, "DATABASE_URL": url, "JWT_SECRET": JWT_SECRET, "ENVIRONMENT": "development",
           "LLM_PROVIDER": "fake", "SANDBOX_BACKEND": "fake", "WORKSPACE_ROOT": tempfile.mkdtemp()}  # fmt: skip
    payload = json.dumps({**seeded, "password": PASSWORD})
    r = subprocess.run([PYTHON, "-c", CHECKS, payload], cwd=BACKEND, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FAIL: verification process crashed\n{r.stderr[-2000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", default=None, help="an EMPTY database (default: a throwaway SQLite file)")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="lf-upgrade-"))
    url = args.database_url or f"sqlite:///{(tmp / 'upgrade.db').as_posix()}"
    sqlite = url.startswith("sqlite")
    sys.path.insert(0, str(BACKEND))
    print(f"[1/5] migrating an empty database to the previous release's head ({PREVIOUS}) ...", file=sys.stderr)
    alembic(url, "upgrade", PREVIOUS)
    print("[2/5] seeding data under the OLD schema ...", file=sys.stderr)
    seeded = seed(url)
    print(f"[3/5] upgrading {PREVIOUS} -> head ({CURRENT}) ...", file=sys.stderr)
    alembic(url, "upgrade", "head")
    print("[4/5] verifying with the NEW code ...", file=sys.stderr)
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    results: dict[str, bool] = {"row_counts_unchanged": counts_of(engine) == seeded["counts"]}
    engine.dispose()
    results.update(verify_new_code(url, seeded))
    engine = sa.create_engine(url)
    after_verify = counts_of(engine)  # the checks themselves write audit rows (logins)
    engine.dispose()
    if sqlite:
        print(f"[5/5] rolling back to {PREVIOUS} and forward again ...", file=sys.stderr)
        alembic(url, "downgrade", PREVIOUS)
        alembic(url, "upgrade", "head")
        engine = sa.create_engine(url)
        results["downgrade_then_upgrade_keeps_core_data"] = counts_of(engine) == after_verify
        engine.dispose()
    else:
        print("[5/5] (rollback round trip is exercised on SQLite only)", file=sys.stderr)
    print(json.dumps({"from": PREVIOUS, "to": CURRENT, "database": url.split(":")[0], "checks": results}, indent=2))
    bad = [k for k, ok in results.items() if not ok]
    if bad:
        print(f"UPGRADE TEST: FAIL {bad}", file=sys.stderr)
        return 1
    print("UPGRADE TEST: PASS", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
