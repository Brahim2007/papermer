#!/bin/sh
set -eu
umask 077

ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

./deploy/check_env.sh "$ENV_FILE"

database_url="$(sed -n 's/^DATABASE_URL=//p' "$ENV_FILE" | tail -n 1)"
case "$BACKUP_DIR" in
  ""|"/"|"."|"..")
    echo "Refusing unsafe BACKUP_DIR: $BACKUP_DIR" >&2
    exit 1
    ;;
esac

mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$BACKUP_DIR/papermetrix-$timestamp.dump"

docker run --rm \
  -e DATABASE_URL="$database_url" \
  -v "$(cd "$BACKUP_DIR" && pwd):/backups" \
  postgres:16-alpine \
  sh -c "pg_dump --format=custom --no-owner --no-acl \"\$DATABASE_URL\" --file=/backups/$(basename "$output")"

find "$BACKUP_DIR" -type f -name 'papermetrix-*.dump' -mtime "+$RETENTION_DAYS" -delete
echo "Encrypted transport database backup created: $output"
