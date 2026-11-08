# Upgrade guide

Always: **back up first** (`scripts/backup.sh`), read the release's section below, upgrade, run migrations, then restart.
`scripts/upgrade_test.py` proves the path from the previous release's schema with seeded data on SQLite and PostgreSQL; it does
not prove your particular data, so rehearse on a restored copy of your own backup when you can.

## The expand / contract rule
A release may only *add* to the schema (new tables, new nullable or defaulted columns). Anything destructive (dropping or renaming a column, tightening a
constraint) ships at least one release after the code stopped using it. That is what makes a rolling deploy safe: the old code keeps working
against the new schema. `docs/operations.md#zero-downtime-migration-policy` has the detail.

## Procedure
1. `bash scripts/backup.sh` (and test the restore if you have not recently).
2. Deploy the new image **without** starting workers; run `alembic upgrade head` once (the compose `migrate` service does this; it takes a PostgreSQL advisory lock so two
   copies cannot race).
3. Start the API, then the workers. Check `/health` (shows the version) and `/health/ready`.
4. Roll back: restore the backup (`scripts/restore.sh`) and redeploy the previous image. `alembic downgrade` exists for development; on production data prefer restore.

## 0.x (Phase 16) -> 1.0.0-rc1  (schema `0011` -> `0013`)
Migrations `0012` and `0013` are additive. What to do and what changes:
* **Secrets are re-encrypted** by migration `0012` (webhook signing secrets: plaintext -> encrypted under the active key). Stored git tokens and TOTP seeds keep their
  existing ciphertext and still decrypt (the implicit `legacy` key). **Do not change `JWT_SECRET` during this upgrade** (it signs live sessions); move the encryption key as described in the next bullet.
* **Production now refuses to start** without `SECRETS_KEY` or `KEYRING_JSON`, or if `SECRETS_KEY` equals `JWT_SECRET`. Before Phase 17 stored git tokens were encrypted with
  `SECRETS_KEY`, or with `JWT_SECRET` when `SECRETS_KEY` was unset. So: set the new distinct `SECRETS_KEY` (or ring), and set **`LEGACY_SECRETS_KEY` to the key your
  tokens are encrypted with today** (the old `SECRETS_KEY`, else the old `JWT_SECRET`). Old values keep decrypting; then run `loopforge keys rotate` to move them to the new key
  and remove `LEGACY_SECRETS_KEY` once `loopforge keys status` shows nothing under `legacy`. A value no key can read is a clear error, never a silent "no token".
* Existing access tokens (no `kid`) stay valid until they expire. Existing passwords, sessions, SSO links, projects, tasks and audit history are untouched.
* New settings (all optional, defaults preserve behaviour): `KEYRING_JSON`, `LEGACY_SECRETS_KEY`, `WEBHOOK_ROTATION_OVERLAP_HOURS`, `OIDC_GROUP_ROLE_MAP_JSON`, `SANDBOX_RUNTIME`,
  `MAX_QUEUED_JOBS*`, `API_TOKEN_RATE_LIMIT_PER_MINUTE` (**default 600/min per API token** - raise it for heavy automation), `USER_RATE_LIMIT_PER_MINUTE`, `PLANS_JSON`.
* Behaviour changes to be aware of: API-token callers can now receive `429`; list endpoints that returned *every* row now return at most 200 (500 for events) per page - follow `Link: rel="next"`;
  `/health` returns an extra `version` field.
* Webhook receivers: signatures are unchanged until you rotate a secret; after rotation, headers carry two `v1=` values for 24 h (`verify_signature` accepts any).
