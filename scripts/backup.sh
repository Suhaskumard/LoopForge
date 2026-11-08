#!/usr/bin/env bash
# PostgreSQL backup: custom-format pg_dump + a tarball of the workspaces + a checksum manifest.
# (Phase 12; encryption and container mode added in Phase 13, ADR-0020.)
#
#   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/loopforge \
#   WORKSPACE_ROOT=/data/workspaces  scripts/backup.sh [output-dir]
#
# Optional environment:
#   PG_CONTAINER=<name>            run pg_dump INSIDE that docker container (no pg_dump needed on the host;
#                                  the credentials/database from DATABASE_URL are used, host/port are ignored)
#   BACKUP_PASSPHRASE_FILE=<file>  encrypt both artifacts with openssl (AES-256-CBC, PBKDF2). NOTE: this
#                                  gives confidentiality; integrity comes from the checksum manifest, which
#                                  is itself unsigned. For authenticated encryption use `age` on the output.
#
# Needs tar and sha256sum; pg_dump (same major version as the server) unless PG_CONTAINER is set.
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-./workspaces}"
OUT="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
PGURL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"   # a plain libpq URL
# GNU tar on Windows (Git Bash) reads "C:/x" as host:path; --force-local makes it a local file
TAR=(tar); case "${OSTYPE:-}" in msys*|cygwin*) TAR=(tar --force-local);; esac

mkdir -p "$OUT"
echo "dumping database ..."
if [ -n "${PG_CONTAINER:-}" ]; then
  # inside the container the server is local: keep user, password and database, drop host:port
  INNER_URL="$(echo "$PGURL" | sed -E 's#(postgresql://[^@]*@)[^/]*(/.*)#\1localhost:5432\2#')"
  docker exec "$PG_CONTAINER" pg_dump --format=custom --no-owner "$INNER_URL" > "$OUT/database.dump"
else
  pg_dump --format=custom --no-owner --file="$OUT/database.dump" "$PGURL"
fi
[ -s "$OUT/database.dump" ] || { echo "pg_dump produced an empty file: aborting"; exit 5; }

echo "archiving workspaces from $WORKSPACE_ROOT ..."
if [ -d "$WORKSPACE_ROOT" ]; then
  "${TAR[@]}" -czf "$OUT/workspaces.tar.gz" -C "$(dirname "$WORKSPACE_ROOT")" "$(basename "$WORKSPACE_ROOT")"
else
  "${TAR[@]}" -czf "$OUT/workspaces.tar.gz" --files-from /dev/null   # an empty archive keeps restore uniform
fi

FILES="database.dump workspaces.tar.gz"
if [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; then
  [ -s "$BACKUP_PASSPHRASE_FILE" ] || { echo "BACKUP_PASSPHRASE_FILE is missing or empty"; exit 6; }
  echo "encrypting ..."
  for f in $FILES; do
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$OUT/$f" -out "$OUT/$f.enc"
    rm -f "$OUT/$f"   # no plaintext copy stays next to the encrypted one
  done
  FILES="database.dump.enc workspaces.tar.gz.enc"
fi
( cd "$OUT" && sha256sum $FILES > manifest.sha256 )
echo "backup complete: $OUT"
cat "$OUT/manifest.sha256"
echo "NOTE: retention deletes from the live database, not from backups. Expire old backups yourself."
