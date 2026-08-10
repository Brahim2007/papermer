from __future__ import annotations

import logging
import os
import sys
import threading

from django.apps import AppConfig


class FrontendConfig(AppConfig):
    name = "frontend"

    def ready(self):
        from django.conf import settings

        if not settings.SEMANTIC_SEARCH_WARMUP_RUNSERVER or "runserver" not in sys.argv:
            return
        if "--noreload" not in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return

        def warm():
            from django.db import close_old_connections
            from frontend.warmup import run_semantic_warmup

            try:
                close_old_connections()
                state = run_semantic_warmup(settings.SEMANTIC_SEARCH_WARMUP_QUERY)
                logging.getLogger(__name__).info("Runserver semantic warm-up: %s", state)
            finally:
                close_old_connections()

        threading.Thread(
            target=warm,
            name="runserver-semantic-warmup",
            daemon=True,
        ).start()
