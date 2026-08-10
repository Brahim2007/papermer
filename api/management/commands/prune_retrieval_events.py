from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import RetrievalEvent


class Command(BaseCommand):
    help = "Delete online retrieval telemetry older than the configured research retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if options["days"] < 1:
            raise CommandError("--days must be at least 1")
        cutoff = timezone.now() - timedelta(days=options["days"])
        queryset = RetrievalEvent.objects.filter(created_at__lt=cutoff)
        count = queryset.count()
        if not options["confirm"]:
            self.stdout.write(f"Would delete {count} event(s) older than {cutoff.isoformat()}.")
            return
        queryset.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} retrieval event(s)."))
