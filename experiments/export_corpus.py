"""Export a deterministic canonical corpus snapshot from a frozen scope."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
from datetime import date, datetime, timezone
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


FIELDS = [
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--parent-corpus", type=Path)
    parser.add_argument("--added-source")
    args = parser.parse_args()

    scope_raw = args.scope.read_bytes()
    scope = json.loads(scope_raw)
    from_date = date.fromisoformat(scope["from_date"])
    to_date = date.fromisoformat(scope["to_date"])

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")
    import django

    django.setup()
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder
    from django.db.models import Count

    from api.models import Article, MetadataEnrichmentAttempt, SourceRecord

    all_articles = Article.objects.all()
    membership = {"policy": "all canonical works within frozen dates"}
    selected = all_articles
    if args.parent_corpus or args.added_source:
        if not args.parent_corpus or not args.added_source:
            raise ValueError(
                "--parent-corpus and --added-source must be supplied together"
            )
        with args.parent_corpus.open(encoding="utf-8", newline="") as handle:
            parent_ids = {
                row["id"] for row in csv.DictReader(handle) if row.get("id")
            }
        added_ids = {
            str(value)
            for value in SourceRecord.objects.filter(
                source=args.added_source,
                article__isnull=False,
            ).values_list("article_id", flat=True)
        }
        selected_ids = parent_ids | added_ids
        selected = all_articles.filter(pk__in=selected_ids)
        membership = {
            "policy": "parent corpus union canonical works from added source",
            "parent_corpus": str(args.parent_corpus),
            "parent_corpus_sha256": file_sha256(args.parent_corpus),
            "parent_document_count": len(parent_ids),
            "added_source": args.added_source,
            "added_source_article_count": len(added_ids),
            "union_identifier_count": len(selected_ids),
        }
    eligible = list(
        selected.filter(
            publication_date__gte=from_date,
            publication_date__lte=to_date,
        ).order_by("pk")
    )
    article_ids = [article.pk for article in eligible]
    enrichment: dict[str, dict] = {}
    attempts = (
        MetadataEnrichmentAttempt.objects.filter(
            article_id__in=article_ids,
            field_name="abstract",
        )
        .order_by("article_id", "provider", "-attempted_at", "-pk")
        .distinct("article_id", "provider")
    )
    for attempt in attempts:
        enrichment.setdefault(str(attempt.article_id), {})[attempt.provider] = {
            "status": attempt.status,
            "reason": attempt.reason,
            "source_identifier": attempt.source_identifier,
            "detail": attempt.detail,
            "attempted_at": attempt.attempted_at.isoformat(),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for article in eligible:
            writer.writerow(
                {
                    "id": str(article.pk),
                    "title": article.title,
                    "abstract": article.abstract,
                    "abstract_enrichment": json.dumps(
                        enrichment.get(str(article.pk), {}),
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                    "keywords": "|".join(article.keywords or ()),
                    "year": article.year or "",
                    "publication_date": (
                        article.publication_date.isoformat()
                        if article.publication_date
                        else ""
                    ),
                    "source": article.source,
                    "venue": article.venue,
                    "publisher": article.publisher,
                    "language": article.language,
                    "type": article.type,
                    "doi": article.doi or "",
                    "arxiv_id": article.arxiv_id or "",
                    "openalex_id": article.openalex_id or "",
                    "semantic_scholar_id": article.semantic_scholar_id or "",
                    "citation_count": article.citation_count,
                    "reference_count": article.reference_count,
                    "is_retracted": article.is_retracted,
                    "is_open_access": article.is_open_access,
                    "topics": "|".join(article.topics or ()),
                    "retrieval_text": article.retrieval_text,
                }
            )
    temporary.replace(args.output)

    total = all_articles.count()
    source_counts = {
        row["source"]: row["count"]
        for row in SourceRecord.objects.values("source")
        .annotate(count=Count("id"))
        .order_by("source")
    }
    manifest_path = args.manifest or args.output.with_suffix(".manifest.json")
    manifest = {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "path": str(args.scope),
            "sha256": file_sha256(args.scope),
            "name": scope["name"],
            "membership": membership,
        },
        "corpus": {
            "path": str(args.output),
            "sha256": file_sha256(args.output),
            "document_count": len(eligible),
            "fields": FIELDS,
            "from_date": from_date.isoformat(),
            "as_of_date": to_date.isoformat(),
            "past_document_count_excluded": all_articles.filter(
                publication_date__lt=from_date
            ).count(),
            "future_document_count_excluded": all_articles.filter(
                publication_date__gt=to_date
            ).count(),
            "missing_date_count_excluded": all_articles.filter(
                publication_date__isnull=True
            ).count(),
        },
        "database": {
            "vendor": connection.vendor,
            "name": connection.settings_dict["NAME"],
            "article_count_before_snapshot_filter": total,
            "source_record_counts": source_counts,
        },
        "schema": {
            "migrations": [
                f"{app}.{name}"
                for app, name in MigrationRecorder.Migration.objects.order_by(
                    "app", "name"
                ).values_list("app", "name")
            ]
        },
        "runtime": {
            "python": platform.python_version(),
            "django": django.get_version(),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["corpus"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
