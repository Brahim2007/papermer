#!/usr/bin/env sh
set -eu

exec celery -A PaperMetrics worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_WORKER_CONCURRENCY:-1}" \
  --max-tasks-per-child="${CELERY_MAX_TASKS_PER_CHILD:-100}"
