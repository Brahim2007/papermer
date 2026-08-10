#!/usr/bin/env sh
set -eu

if [ "${WAIT_FOR_DATABASE:-1}" = "1" ]; then
  python manage.py wait_for_database \
    --timeout "${DATABASE_WAIT_TIMEOUT:-90}" \
    --interval "${DATABASE_WAIT_INTERVAL:-2}"
fi

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${COLLECT_STATIC:-0}" = "1" ]; then
  python manage.py collectstatic --noinput --clear
fi

exec "$@"
