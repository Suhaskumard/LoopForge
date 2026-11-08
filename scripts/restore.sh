#!/usr/bin/env bash
# PostgreSQL restore from scripts/backup.sh output. (Phase 12, ADR-0019.) NOT RUN in the development
# environment. It REPLACES the target database's contents, so it refuses to run without --yes.
#
#   DATABASE_URL=postgresql+psycopg://... WORKSPACE_ROOT=/data/workspaces \
#   scripts/restore.sh <backup-dir> --yes
#
# Stop the API and all workers first. Afterwards run the migrations (`alembic upgrade head`) in case the
# backup is from an older release, then start the services.
set -euo pipefail

BACKUP="${1:?usage: restore.sh <backup-dir> --yes}"
[ "${2:-}" = "--yes" ] || { echo "refusing to overwrite the database without --yes"; exit 2; }
: "${DATABASE_URL:?set DATABASE_URL}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-./workspaces}"
PGURL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

echo "verifying checksums ..."
( cd "$BACKUP" && sha256sum --check manifest.sha256 ) || { echo "backup is corrupt: aborting"; exit 3; }

echo "restoring database ..."
pg_restore --clean --if-exists --no-owner --dbname="$PGURL" "$BACKUP/database.dump"

echo "restoring workspaces to $WORKSPACE_ROOT ..."
# refuse archives with absolute paths or '..' members before extracting
if tar -tzf "$BACKUP/workspaces.tar.gz" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "unsafe path in workspaces archive: aborting"; exit 4
fi
rm -rf "$WORKSPACE_ROOT"
mkdir -p "$(dirname "$WORKSPACE_ROOT")"
tar -xzf "$BACKUP/workspaces.tar.gz" -C "$(dirname "$WORKSPACE_ROOT")"
echo "restore complete. Next: alembic upgrade head, then start the services, then check /health/ready."
