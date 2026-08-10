"""Export a deterministic corpus snapshot for retrieval experiments."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
from datetime import date, datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/corpus.csv"))
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Defaults to the corpus path with a .manifest.json suffix.",
    )
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        help="Exclude works whose known publication date is after this date.",
    )
    parser.add_argument(
        "--from-date",
        type=date.fromisoformat,
        help="Exclude works whose known publication date is before this date.",
    )
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")
    import django

    django.setup()
    from django import get_version as django_version
    from django.db import connection
    from django.db.models import Count, Q

    from api.models import Article, SourceRecord

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "title",
        "abstract",
        "abstract_enrichment",
        "keywords",
        "year",
        "publication_date",
        "source",
        "venue",
        "publisher",
        "language",
        "type",
        "doi",
        "arxiv_id",
        "openalex_id",
        "semantic_scholar_id",
        "citation_count",
        "reference_count",
        "is_retracted",
        "is_open_access",
        "topics",
        "retrieval_text",
    ]
    articles = Article.objects.order_by("pk").prefetch_related(
        "metadata_enrichment_attempts"
    )
    future_excluded = 0
    past_excluded = 0
    if (
        args.from_date
        and args.as_of_date
        and args.as_of_date < args.from_date
    ):
        raise ValueError("--as-of-date must not precede --from-date")
    if args.from_date:
        past_excluded = articles.filter(
            publication_date__lt=args.from_date
        ).count()
        articles = articles.filter(
            Q(publication_date__isnull=True)
            | Q(publication_date__gte=args.from_date)
        )
    if args.as_of_date:
        future_excluded = articles.filter(
            publication_date__gt=args.as_of_date
        ).count()
        articles = articles.filter(
            Q(publication_date__isnull=True)
            | Q(publication_date__lte=args.as_of_date)
        )
    exported_count = articles.count()
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for article in articles.iterator(chunk_size=500):
            latest_attempts = {}
            for attempt in article.metadata_enrichment_attempts.all():
                previous = latest_attempts.get(attempt.provider)
                if previous is None or attempt.attempted_at > previous.attempted_at:
                    latest_attempts[attempt.provider] = attempt
            abstract_enrichment = {
                provider: {
                    "status": attempt.status,
                    "reason": attempt.reason,
                    "attempted_at": attempt.attempted_at.isoformat(),
                }
                for provider, attempt in sorted(latest_attempts.items())
            }
            writer.writerow(
                {
                    "id": article.pk,
                    "title": article.title,
                    "abstract": article.abstract,
                    "abstract_enrichment": json.dumps(
                        abstract_enrichment,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "keywords": "|".join(article.keywords or []),
                    "year": article.year or "",
                    "publication_date": article.publication_date or "",
                    "source": article.source,
                    "venue": article.venue,
                    "publisher": article.publisher,
                    "language": article.language,
                    "type": article.type,
                    "doi": article.doi or article.identifiers.get("doi", ""),
                    "arxiv_id": article.arxiv_id or "",
                    "openalex_id": article.openalex_id or "",
                    "semantic_scholar_id": article.semantic_scholar_id or "",
                    "citation_count": article.citation_count,
                    "reference_count": article.reference_count,
                    "is_retracted": article.is_retracted,
                    "is_open_access": article.is_open_access,
                    "topics": "|".join(article.topics or []),
                    "retrieval_text": article.retrieval_text,
                }
            )

    digest = hashlib.sha256()
    with args.output.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    manifest_path = args.manifest or args.output.with_suffix(".manifest.json")
    source_counts = {
        row["source"]: row["count"]
        for row in SourceRecord.objects.values("source")
        .annotate(count=Count("id"))
        .order_by("source")
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "select app, name from django_migrations order by app, applied, name"
        )
        migrations = [f"{app}.{name}" for app, name in cursor.fetchall()]
    manifest = {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "path": str(args.output),
            "sha256": digest.hexdigest(),
            "document_count": exported_count,
            "fields": fields,
            "as_of_date": args.as_of_date.isoformat() if args.as_of_date else None,
            "from_date": args.from_date.isoformat() if args.from_date else None,
            "past_document_count_excluded": past_excluded,
            "future_document_count_excluded": future_excluded,
        },
        "database": {
            "vendor": connection.vendor,
            "name": connection.settings_dict["NAME"],
            "source_record_counts": source_counts,
            "article_count_before_snapshot_filter": Article.objects.count(),
        },
        "schema": {"migrations": migrations},
        "runtime": {
            "python": platform.python_version(),
            "django": django_version(),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        f"Exported {manifest['corpus']['document_count']} papers to {args.output} "
        f"(sha256={digest.hexdigest()})"
    )
    print(f"Wrote manifest to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
