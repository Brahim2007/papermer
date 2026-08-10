#!/bin/sh
set -eu

ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_FILE="${1:-}"

if [ "${RESTORE_CONFIRM:-}" != "restore-papermetrix" ]; then
  echo "Restore changes the target database. Set RESTORE_CONFIRM=restore-papermetrix explicitly." >&2
  exit 1
fi
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
  echo "Usage: RESTORE_CONFIRM=restore-papermetrix $0 <backup.dump>" >&2
  exit 1
fi

./deploy/check_env.sh "$ENV_FILE"
database_url="$(sed -n 's/^DATABASE_URL=//p' "$ENV_FILE" | tail -n 1)"
backup_dir="$(cd "$(dirname "$BACKUP_FILE")" && pwd)"
backup_name="$(basename "$BACKUP_FILE")"

docker run --rm \
  -e DATABASE_URL="$database_url" \
  -v "$backup_dir:/backups:ro" \
  postgres:16-alpine \
  sh -c "pg_restore --clean --if-exists --no-owner --no-acl --dbname=\"\$DATABASE_URL\" \"/backups/$backup_name\""

echo "Database restore completed from: $BACKUP_FILE"
