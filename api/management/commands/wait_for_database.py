from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection


class Command(BaseCommand):
    help = "Wait until the configured default database accepts a query."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        timeout = options["timeout"]
        interval = options["interval"]
        if timeout < 1 or interval <= 0:
            raise CommandError("timeout and interval must be positive")
        deadline = time.monotonic() + timeout
        while True:
            try:
                connection.close()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                self.stdout.write(self.style.SUCCESS("Database is ready."))
                return
            except OperationalError as exc:
                if time.monotonic() >= deadline:
                    raise CommandError(
                        f"database was not ready within {timeout} seconds"
                    ) from exc
                self.stdout.write("Database unavailable; retrying...")
                time.sleep(interval)
