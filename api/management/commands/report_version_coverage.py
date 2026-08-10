from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from api.models import Article, MetadataEnrichmentAttempt, WorkVersion


class Command(BaseCommand):
    help = "Write a machine-readable work-version and open-access coverage report."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, required=True)

    def handle(self, *args, **options):
        total = Article.objects.count()
        versioned = Article.objects.filter(versions__isnull=False).distinct().count()
        multi_version = (
            Article.objects.annotate(version_count=Count("versions"))
            .filter(version_count__gt=1)
            .count()
        )
        latest_oa_attempts = (
            MetadataEnrichmentAttempt.objects.filter(field_name="open_access")
            .order_by("article_id", "-attempted_at", "-pk")
            .distinct("article_id")
        )
        latest_status: dict[str, int] = {}
        for status in latest_oa_attempts.values_list("status", flat=True):
            latest_status[status] = latest_status.get(status, 0) + 1
        report = {
            "format_version": 1,
            "generated_at": timezone.now().isoformat(),
            "scope": "current canonical database; frozen corpus artifacts unchanged",
            "works": {
                "total": total,
                "with_doi": Article.objects.exclude(doi__isnull=True)
                .exclude(doi="")
                .count(),
                "with_arxiv_id": Article.objects.exclude(arxiv_id__isnull=True)
                .exclude(arxiv_id="")
                .count(),
                "marked_open_access": Article.objects.filter(
                    is_open_access=True
                ).count(),
                "with_versions": versioned,
                "with_multiple_versions": multi_version,
                "version_coverage": versioned / total if total else 0.0,
            },
            "versions": {
                "total": WorkVersion.objects.count(),
                "by_type": self._counts(WorkVersion.objects.all(), "version_type"),
                "by_source": self._counts(WorkVersion.objects.all(), "source"),
                "by_oa_status": self._counts(
                    WorkVersion.objects.all(), "oa_status", empty="unspecified"
                ),
                "with_pdf": WorkVersion.objects.exclude(pdf_url__isnull=True)
                .exclude(pdf_url="")
                .count(),
                "open_access": WorkVersion.objects.filter(
                    is_open_access=True
                ).count(),
            },
            "open_access_enrichment": {
                "latest_status_by_work": latest_status,
                "attempt_events": self._counts(
                    MetadataEnrichmentAttempt.objects.filter(
                        field_name="open_access"
                    ),
                    "status",
                ),
            },
        }
        output: Path = options["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
        self.stdout.write(self.style.SUCCESS(json.dumps(report["works"])))

    @staticmethod
    def _counts(queryset, field: str, *, empty: str = "") -> dict[str, int]:
        return {
            (row[field] or empty): row["count"]
            for row in queryset.values(field)
            .annotate(count=Count("id"))
            .order_by(field)
        }
