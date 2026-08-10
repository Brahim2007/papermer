from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import (
    Article,
    MetadataEnrichmentAttempt,
    SourceRecord,
    WorkVersion,
)
from scholarly.connectors import ConnectorRequestError, UnpaywallConnector
from scholarly.versions import location_external_id, version_type


class Command(BaseCommand):
    help = "Enrich DOI works with auditable Unpaywall OA locations and versions."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--article-id", action="append", default=[])
        parser.add_argument("--retry-terminal", action="store_true")

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        if not settings.UNPAYWALL_EMAIL:
            raise CommandError(
                "UNPAYWALL_EMAIL (or CROSSREF_EMAIL) must contain a contact email"
            )
        connector = UnpaywallConnector(
            email=settings.UNPAYWALL_EMAIL,
            min_interval_seconds=settings.UNPAYWALL_MIN_INTERVAL_SECONDS,
        )
        articles = Article.objects.exclude(doi__isnull=True).exclude(doi="")
        if options["article_id"]:
            articles = articles.filter(pk__in=options["article_id"])
        if not options["retry_terminal"]:
            terminal_ids = MetadataEnrichmentAttempt.objects.filter(
                field_name="open_access",
                provider="unpaywall",
                status__in={
                    "enriched",
                    "provider_no_open_access",
                    "not_found",
                },
            ).values_list("article_id", flat=True)
            articles = articles.exclude(pk__in=terminal_ids)
        selected = list(articles.order_by("pk")[: options["limit"]])

        source_records: list[SourceRecord] = []
        versions: list[WorkVersion] = []
        attempts: list[MetadataEnrichmentAttempt] = []
        article_updates: list[Article] = []
        counts: dict[str, int] = {}

        for article in selected:
            try:
                record = connector.lookup(article.doi)
            except ConnectorRequestError as exc:
                attempts.append(
                    self._attempt(
                        article,
                        "request_error",
                        str(exc),
                        detail={"http_status": exc.status_code},
                    )
                )
                counts["request_error"] = counts.get("request_error", 0) + 1
                if exc.status_code in {401, 403}:
                    break
                continue
            if record is None:
                attempts.append(
                    self._attempt(
                        article,
                        "not_found",
                        "Unpaywall has no record for this DOI",
                    )
                )
                counts["not_found"] = counts.get("not_found", 0) + 1
                continue

            retrieved = timezone.now()
            canonical_payload = json.dumps(
                record.raw_payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            source_records.append(
                SourceRecord(
                    source="unpaywall",
                    external_id=record.doi,
                    article=article,
                    payload=record.raw_payload,
                    payload_checksum=hashlib.sha256(
                        canonical_payload.encode("utf-8")
                    ).hexdigest(),
                    retrieved_at=retrieved,
                )
            )
            best_pdf = None
            best_landing = None
            for location in record.locations:
                versions.append(
                    WorkVersion(
                        article=article,
                        source="unpaywall",
                        external_id=location_external_id(
                            record.doi,
                            location.landing_url,
                            location.pdf_url,
                            location.version,
                        ),
                        version_type=version_type(location.version),
                        version_label=location.version,
                        publication_date=record.oa_date,
                        landing_url=location.landing_url,
                        pdf_url=location.pdf_url,
                        doi=record.doi,
                        is_open_access=True,
                        license=location.license,
                        host_type=location.host_type,
                        oa_status=record.oa_status,
                        provenance={
                            "provider": "unpaywall",
                            "retrieved_at": retrieved.isoformat(),
                            "is_best": location.is_best,
                            "location": location.raw_payload,
                        },
                        created_at=retrieved,
                        updated_at=retrieved,
                    )
                )
                if location.is_best:
                    best_pdf = location.pdf_url
                    best_landing = location.landing_url

            if record.is_open_access:
                article.is_open_access = True
                article.pdf = article.pdf or best_pdf
                article.link = article.link or best_landing or ""
                article.provenance = dict(article.provenance or {})
                article.provenance["open_access"] = {
                    "source": "unpaywall",
                    "external_id": record.doi,
                    "retrieved_at": retrieved.isoformat(),
                    "oa_status": record.oa_status,
                }
                article.updated_on = retrieved
                article_updates.append(article)
                status = "enriched" if record.locations else "provider_no_location"
                reason = (
                    "open-access locations stored as work versions"
                    if record.locations
                    else "DOI is open access but no usable location was returned"
                )
            else:
                status = "provider_no_open_access"
                reason = "Unpaywall classifies this DOI as closed"
            attempts.append(
                self._attempt(
                    article,
                    status,
                    reason,
                    detail={
                        "oa_status": record.oa_status,
                        "location_count": len(record.locations),
                    },
                )
            )
            counts[status] = counts.get(status, 0) + 1

        self._flush(source_records, versions, article_updates, attempts)
        summary = ", ".join(
            f"{status}={count}" for status, count in sorted(counts.items())
        )
        self.stdout.write(self.style.SUCCESS(summary or "no eligible DOI works"))

    @staticmethod
    def _flush(
        source_records: list[SourceRecord],
        versions: list[WorkVersion],
        articles: list[Article],
        attempts: list[MetadataEnrichmentAttempt],
    ) -> None:
        if source_records:
            SourceRecord.objects.bulk_create(
                source_records,
                update_conflicts=True,
                unique_fields=["source", "external_id"],
                update_fields=[
                    "article",
                    "payload",
                    "payload_checksum",
                    "retrieved_at",
                ],
            )
        if versions:
            unique_versions: dict[tuple[str, str], WorkVersion] = {}
            for work_version in versions:
                key = (work_version.source, work_version.external_id)
                existing = unique_versions.get(key)
                if existing is None or work_version.provenance.get("is_best"):
                    unique_versions[key] = work_version
            WorkVersion.objects.bulk_create(
                list(unique_versions.values()),
                update_conflicts=True,
                unique_fields=["source", "external_id"],
                update_fields=[
                    "article",
                    "version_type",
                    "version_label",
                    "publication_date",
                    "landing_url",
                    "pdf_url",
                    "doi",
                    "is_open_access",
                    "license",
                    "host_type",
                    "oa_status",
                    "provenance",
                    "updated_at",
                ],
            )
        if articles:
            Article.objects.bulk_update(
                articles,
                ["is_open_access", "pdf", "link", "provenance", "updated_on"],
            )
            WorkVersion.objects.filter(
                source="canonical_doi",
                article_id__in=[article.pk for article in articles],
            ).update(is_open_access=True)
        if attempts:
            MetadataEnrichmentAttempt.objects.bulk_create(attempts)

    @staticmethod
    def _attempt(
        article: Article, status: str, reason: str, *, detail: dict | None = None
    ) -> MetadataEnrichmentAttempt:
        return MetadataEnrichmentAttempt(
            article=article,
            field_name="open_access",
            provider="unpaywall",
            status=status,
            reason=reason[:255],
            source_identifier=article.doi or "",
            detail=detail or {},
        )
