from __future__ import annotations

import os
import threading


bind = "0.0.0.0:8000"
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))
worker_tmp_dir = "/dev/shm"
accesslog = "-"
errorlog = "-"
capture_output = True
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "*")


def post_worker_init(worker):
    """Warm the optional dense retriever without delaying the health endpoint."""
    query = os.getenv("SEMANTIC_SEARCH_WARMUP_QUERY", "").strip()
    if not query:
        return

    def warm():
        from django.db import close_old_connections

        try:
            from frontend.warmup import run_semantic_warmup

            close_old_connections()
            state = run_semantic_warmup(query)
            if state["status"] == "ready":
                worker.log.info(
                    "Semantic search warm-up completed in %.1f ms",
                    state["latency_ms"],
                )
            else:
                worker.log.error("Semantic search warm-up degraded: %s", state)
        except Exception:
            worker.log.exception("Semantic search warm-up failed; sparse fallback remains available")
        finally:
            close_old_connections()

    threading.Thread(target=warm, name="semantic-search-warmup", daemon=True).start()
