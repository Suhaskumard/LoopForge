#!/usr/bin/env bash
# PostgreSQL backup: custom-format pg_dump + a tarball of the workspaces + a checksum manifest.
# (Phase 12, ADR-0019.) NOT RUN in the development environment (no PostgreSQL there): rehearse it, and
# rehearse scripts/restore.sh on a scratch database, before you rely on it.
#
#   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/loopforge \
#   WORKSPACE_ROOT=/data/workspaces  scripts/backup.sh [output-dir]
#
# Needs pg_dump (same major version as the server) and tar on PATH.
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-./workspaces}"
OUT="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
PGURL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"   # pg_dump wants a plain libpq URL

mkdir -p "$OUT"
echo "dumping database ..."
pg_dump --format=custom --no-owner --file="$OUT/database.dump" "$PGURL"
echo "archiving workspaces from $WORKSPACE_ROOT ..."
if [ -d "$WORKSPACE_ROOT" ]; then
  tar -czf "$OUT/workspaces.tar.gz" -C "$(dirname "$WORKSPACE_ROOT")" "$(basename "$WORKSPACE_ROOT")"
else
  tar -czf "$OUT/workspaces.tar.gz" --files-from /dev/null   # an empty archive keeps restore uniform
fi
( cd "$OUT" && sha256sum database.dump workspaces.tar.gz > manifest.sha256 )
echo "backup complete: $OUT"
cat "$OUT/manifest.sha256"
echo "NOTE: retention deletes from the live database, not from backups. Expire old backups yourself."
