#!/usr/bin/env sh
set -eu

exec celery -A PaperMetrics beat \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler
