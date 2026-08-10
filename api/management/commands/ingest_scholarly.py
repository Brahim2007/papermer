from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from scholarly.connectors import (
    ArxivConnector,
    ConnectorRequestError,
    CrossrefConnector,
    OpenAlexConnector,
    SemanticScholarConnector,
)
from scholarly.ingest import ingest_records


class Command(BaseCommand):
    help = "Search a scholarly metadata provider and ingest canonical records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            choices=("openalex", "semantic_scholar", "crossref", "arxiv"),
        )
        parser.add_argument("--query", required=True)
        parser.add_argument("--limit", type=int, default=25)

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["limit"] > 100:
            raise CommandError("--limit must be between 1 and 100")
        connectors = {
            "openalex": OpenAlexConnector(email=settings.OPENALEX_EMAIL),
            "semantic_scholar": SemanticScholarConnector(
                api_key=settings.SEMANTIC_SCHOLAR_API_KEY,
                min_interval_seconds=settings.SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS,
            ),
            "crossref": CrossrefConnector(email=settings.CROSSREF_EMAIL),
            "arxiv": ArxivConnector(
                min_interval_seconds=settings.ARXIV_MIN_INTERVAL_SECONDS
            ),
        }
        connector = connectors[options["source"]]
        try:
            records = connector.search(options["query"], limit=options["limit"])
        except ConnectorRequestError as exc:
            raise CommandError(str(exc)) from exc
        results = ingest_records(records)
        created = sum(result.created for result in results)
        self.stdout.write(
            self.style.SUCCESS(
                f"Ingested {len(results)} records ({created} new, "
                f"{len(results) - created} updated) from {options['source']}."
            )
        )
