#!/usr/bin/env bash
# PostgreSQL restore from scripts/backup.sh output. (Phase 12; encryption and container mode: Phase 13.)
# It REPLACES the target database's contents, so it refuses to run without --yes.
#
#   DATABASE_URL=postgresql+psycopg://... WORKSPACE_ROOT=/data/workspaces \
#   scripts/restore.sh <backup-dir> --yes
#
# Optional environment (same meaning as in backup.sh): PG_CONTAINER=<name>, BACKUP_PASSPHRASE_FILE=<file>.
# Stop the API and all workers first. Afterwards run the migrations (`alembic upgrade head`) in case the
# backup is from an older release, then start the services.
set -euo pipefail

BACKUP="${1:?usage: restore.sh <backup-dir> --yes}"
[ "${2:-}" = "--yes" ] || { echo "refusing to overwrite the database without --yes"; exit 2; }
: "${DATABASE_URL:?set DATABASE_URL}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-./workspaces}"
PGURL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
# GNU tar on Windows (Git Bash) reads "C:/x" as host:path; --force-local makes it a local file
TAR=(tar); case "${OSTYPE:-}" in msys*|cygwin*) TAR=(tar --force-local);; esac

echo "verifying checksums ..."
( cd "$BACKUP" && sha256sum --check manifest.sha256 ) || { echo "backup is corrupt: aborting"; exit 3; }

DUMP="$BACKUP/database.dump"; ARCHIVE="$BACKUP/workspaces.tar.gz"; SCRATCH=""
trap '[ -n "$SCRATCH" ] && rm -rf "$SCRATCH"' EXIT
if [ -f "$BACKUP/database.dump.enc" ]; then
  [ -n "${BACKUP_PASSPHRASE_FILE:-}" ] || { echo "this backup is encrypted: set BACKUP_PASSPHRASE_FILE"; exit 6; }
  SCRATCH="$(mktemp -d)"
  echo "decrypting ..."
  for f in database.dump workspaces.tar.gz; do
    openssl enc -d -aes-256-cbc -pbkdf2 -pass "file:$BACKUP_PASSPHRASE_FILE" \
        -in "$BACKUP/$f.enc" -out "$SCRATCH/$f" || { echo "cannot decrypt $f: wrong passphrase or damaged backup"; exit 7; }
  done
  DUMP="$SCRATCH/database.dump"; ARCHIVE="$SCRATCH/workspaces.tar.gz"
fi

echo "restoring database ..."
if [ -n "${PG_CONTAINER:-}" ]; then
  INNER_URL="$(echo "$PGURL" | sed -E 's#(postgresql://[^@]*@)[^/]*(/.*)#\1localhost:5432\2#')"
  docker exec -i "$PG_CONTAINER" pg_restore --clean --if-exists --no-owner --dbname="$INNER_URL" < "$DUMP"
else
  pg_restore --clean --if-exists --no-owner --dbname="$PGURL" "$DUMP"
fi

echo "restoring workspaces to $WORKSPACE_ROOT ..."
# refuse archives with absolute paths or '..' members before extracting
if "${TAR[@]}" -tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "unsafe path in workspaces archive: aborting"; exit 4
fi
rm -rf "$WORKSPACE_ROOT"
mkdir -p "$(dirname "$WORKSPACE_ROOT")"
"${TAR[@]}" -xzf "$ARCHIVE" -C "$(dirname "$WORKSPACE_ROOT")"
echo "restore complete. Next: alembic upgrade head, then start the services, then check /health/ready."
