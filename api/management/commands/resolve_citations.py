from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Backfill cited_article links from normalized work identifiers."

    @transaction.atomic
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE api_citation AS citation
                   SET cited_article_id = identifier.article_id
                  FROM api_workidentifier AS identifier
                 WHERE citation.cited_article_id IS NULL
                   AND identifier.scheme = citation.identifier_scheme
                   AND identifier.normalized_value = citation.cited_identifier
                   AND identifier.article_id <> citation.citing_article_id
                """
            )
            updated = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(f"Resolved {updated} citation edges.")
        )
