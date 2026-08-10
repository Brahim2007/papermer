from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.models import Article, MetadataEnrichmentAttempt
from scholarly.connectors import (
    ConnectorRequestError,
    OpenAlexConnector,
    SemanticScholarConnector,
)
from scholarly.ingest import ingest_record


class Command(BaseCommand):
    help = "Enrich missing abstracts and retain an auditable outcome per provider."

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            action="append",
            choices=("openalex", "semantic_scholar"),
            dest="providers",
        )
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--article-id", action="append", default=[])
        parser.add_argument(
            "--retry-terminal",
            action="store_true",
            help="Repeat not-found/no-abstract attempts for the selected providers.",
        )

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        providers = options["providers"] or ["openalex", "semantic_scholar"]
        connectors = {
            "openalex": OpenAlexConnector(email=settings.OPENALEX_EMAIL),
            "semantic_scholar": SemanticScholarConnector(
                api_key=settings.SEMANTIC_SCHOLAR_API_KEY,
                min_interval_seconds=settings.SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS,
            ),
        }
        articles = Article.objects.filter(abstract="").order_by("pk")
        if options["article_id"]:
            articles = articles.filter(pk__in=options["article_id"])
        articles = list(articles[: options["limit"]])
        unavailable: dict[str, str] = {}
        counts: dict[str, int] = {}

        for article in articles:
            for provider in providers:
                if article.abstract.strip():
                    break
                if (
                    not options["retry_terminal"]
                    and MetadataEnrichmentAttempt.objects.filter(
                        article=article,
                        field_name="abstract",
                        provider=provider,
                        status__in={
                            "provider_no_abstract",
                            "not_found",
                            "no_identifier",
                            "identity_mismatch",
                        },
                    ).exists()
                ):
                    continue
                if provider in unavailable:
                    self._record(
                        article,
                        provider,
                        "request_error",
                        "provider disabled after authentication/authorization failure",
                        detail={"error": unavailable[provider], "circuit_open": True},
                    )
                    counts["request_error"] = counts.get("request_error", 0) + 1
                    continue
                source_identifier = self._source_identifier(article, provider)
                if not source_identifier:
                    self._record(
                        article,
                        provider,
                        "no_identifier",
                        "no provider-supported identifier is available",
                    )
                    counts["no_identifier"] = counts.get("no_identifier", 0) + 1
                    continue
                try:
                    record = self._lookup(connectors[provider], article, provider)
                except ConnectorRequestError as exc:
                    message = str(exc)
                    self._record(
                        article,
                        provider,
                        "request_error",
                        message,
                        source_identifier=source_identifier,
                        detail={"http_status": exc.status_code},
                    )
                    counts["request_error"] = counts.get("request_error", 0) + 1
                    if exc.status_code in {401, 403}:
                        unavailable[provider] = message
                    continue
                if record is None:
                    self._record(
                        article,
                        provider,
                        "not_found",
                        "provider returned no identity-safe match",
                        source_identifier=source_identifier,
                    )
                    counts["not_found"] = counts.get("not_found", 0) + 1
                    continue
                if not record.abstract.strip():
                    self._record(
                        article,
                        provider,
                        "provider_no_abstract",
                        "matched provider record has no abstract",
                        source_identifier=source_identifier,
                        detail={"external_id": record.external_id},
                    )
                    counts["provider_no_abstract"] = (
                        counts.get("provider_no_abstract", 0) + 1
                    )
                    continue
                result = ingest_record(record)
                if result.article_id != str(article.pk):
                    self._record(
                        article,
                        provider,
                        "identity_mismatch",
                        "provider record resolved to a different canonical work",
                        source_identifier=source_identifier,
                        detail={
                            "resolved_article_id": result.article_id,
                            "external_id": record.external_id,
                        },
                    )
                    counts["identity_mismatch"] = (
                        counts.get("identity_mismatch", 0) + 1
                    )
                    continue
                article.refresh_from_db(fields=["abstract"])
                status = "enriched" if article.abstract.strip() else "write_failed"
                self._record(
                    article,
                    provider,
                    status,
                    "abstract stored with source provenance"
                    if status == "enriched"
                    else "ingest completed but abstract remains blank",
                    source_identifier=source_identifier,
                    detail={
                        "external_id": record.external_id,
                        "abstract_characters": len(article.abstract),
                    },
                )
                counts[status] = counts.get(status, 0) + 1

        remaining = Article.objects.filter(abstract="").count()
        summary = ", ".join(
            f"{status}={count}" for status, count in sorted(counts.items())
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {len(articles)} missing-abstract works; "
                f"{summary or 'no attempts'}; remaining_missing={remaining}."
            )
        )

    @staticmethod
    def _source_identifier(article: Article, provider: str) -> str:
        if provider == "openalex":
            return (
                article.openalex_id
                or article.doi
                or (f"title:{article.normalized_title}:{article.year}")
            )
        return (
            article.semantic_scholar_id
            or (f"DOI:{article.doi}" if article.doi else "")
            or (f"ARXIV:{article.arxiv_id}" if article.arxiv_id else "")
        )

    @staticmethod
    def _lookup(connector, article: Article, provider: str):
        if provider == "openalex":
            return connector.lookup(
                openalex_id=article.openalex_id or "",
                doi=article.doi or "",
                title=article.title,
                year=article.year,
            )
        return connector.lookup(
            semantic_scholar_id=article.semantic_scholar_id or "",
            doi=article.doi or "",
            arxiv_id=article.arxiv_id or "",
        )

    @staticmethod
    def _record(
        article: Article,
        provider: str,
        status: str,
        reason: str,
        *,
        source_identifier: str = "",
        detail: dict | None = None,
    ) -> None:
        MetadataEnrichmentAttempt.objects.create(
            article=article,
            field_name="abstract",
            provider=provider,
            status=status,
            reason=reason[:255],
            source_identifier=source_identifier,
            detail=detail or {},
        )
