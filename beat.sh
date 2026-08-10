#!/usr/bin/env sh
set -eu
celery -A PaperMetrics beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
