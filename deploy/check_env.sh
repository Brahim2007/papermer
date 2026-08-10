#!/bin/sh
set -eu

ENV_FILE="${1:-.env.production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing environment file: $ENV_FILE" >&2
  exit 1
fi

required_vars="
APP_DOMAIN
ACME_EMAIL
DJANGO_SECRET_KEY
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
DATABASE_URL
REDIS_PASSWORD
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
DJANGO_CACHE_URL
"

failed=0
for variable in $required_vars; do
  value="$(sed -n "s/^${variable}=//p" "$ENV_FILE" | tail -n 1)"
  case "$value" in
    ""|*replace-*|*changeme*|*example.org*|*user:password*|*"<"*|*">"*)
      echo "Missing or placeholder value: $variable" >&2
      failed=1
      ;;
  esac
done

if grep -Eq '^(DJANGO_DEBUG=true|DJANGO_SECURE_SSL_REDIRECT=false)' "$ENV_FILE"; then
  echo "Unsafe Django production setting found." >&2
  failed=1
fi

if [ "$failed" -ne 0 ]; then
  exit 1
fi

if command -v stat >/dev/null 2>&1; then
  mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
  if [ -n "$mode" ] && [ "$mode" != "600" ]; then
    echo "Warning: set $ENV_FILE permissions to 600 (current: $mode)." >&2
  fi
fi

echo "Production environment validation passed."
