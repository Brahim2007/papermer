#!/usr/bin/env sh
set -eu
celery -A PaperMetrics worker --loglevel=info
