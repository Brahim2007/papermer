from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.models import Article, WorkVersion


class Command(BaseCommand):
    help = "Create conservative version rows from existing canonical identifiers."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        candidates = []
        for article in Article.objects.order_by("pk")[: options["limit"]]:
            if article.doi:
                candidates.append(
                    WorkVersion(
                        article=article,
                        source="canonical_doi",
                        external_id=article.doi,
                        version_type="published",
                        version_label="publishedVersion",
                        publication_date=article.publication_date,
                        landing_url=article.link or f"https://doi.org/{article.doi}",
                        pdf_url=article.pdf,
                        doi=article.doi,
                        is_open_access=article.is_open_access,
                        provenance={
                            "method": "conservative_backfill",
                            "source": "canonical_article",
                        },
                    )
                )
            if article.arxiv_id:
                candidates.append(
                    WorkVersion(
                        article=article,
                        source="canonical_arxiv",
                        external_id=article.arxiv_id,
                        version_type="submitted",
                        publication_date=article.publication_date,
                        landing_url=f"https://arxiv.org/abs/{article.arxiv_id}",
                        pdf_url=f"https://arxiv.org/pdf/{article.arxiv_id}",
                        doi=article.doi,
                        arxiv_id=article.arxiv_id,
                        is_open_access=True,
                        provenance={
                            "method": "conservative_backfill",
                            "source": "canonical_article",
                            "version_number_known": False,
                        },
                    )
                )
        before = WorkVersion.objects.count()
        WorkVersion.objects.bulk_create(candidates, ignore_conflicts=True)
        created = WorkVersion.objects.count() - before
        self.stdout.write(
            self.style.SUCCESS(
                f"Backfilled {created} new identifier-derived version rows "
                f"from {len(candidates)} candidates."
            )
        )
