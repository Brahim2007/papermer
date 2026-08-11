# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS builder

ARG REQUIREMENTS_FILE=requirements/production.txt
ARG TORCH_INDEX_URL=
ARG TORCH_VERSION=
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements/ requirements/
RUN if [ -n "${TORCH_INDEX_URL}" ]; then \
        test -n "${TORCH_VERSION}"; \
        python -m pip wheel \
            --wheel-dir /wheels \
            --index-url "${TORCH_INDEX_URL}" \
            "torch==${TORCH_VERSION}"; \
    fi \
    && python -m pip wheel \
        --wheel-dir /wheels \
        --find-links /wheels \
        --requirement "${REQUIREMENTS_FILE}"


FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=PaperMetrics.settings

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libgomp1 \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/* \
    && rm -rf /wheels

COPY --chown=app:app . /app
RUN chmod 0555 /app/deploy/entrypoint.sh \
    /app/deploy/worker.sh \
    /app/deploy/beat.sh \
    && mkdir -p /app/staticfiles /app/media /app/.cache/huggingface \
    && chown -R app:app /app/staticfiles /app/media /app/.cache

USER app

EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "PaperMetrics.wsgi:application", "--config", "deploy/gunicorn.conf.py"]
