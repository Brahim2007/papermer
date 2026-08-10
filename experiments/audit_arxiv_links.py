"""Audit canonical arXiv identifiers, versions, and DOI links."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256
from scholarly.normalize import normalize_arxiv_id, normalize_doi


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acquisition-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on-violation", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")
    import django

    django.setup()
    from api.models import Article, SourceRecord, WorkVersion

    records = list(
        SourceRecord.objects.filter(source="arxiv")
        .select_related("article")
        .order_by("external_id")
    )
    versions = {
        version.external_id: version
        for version in WorkVersion.objects.filter(source="arxiv")
    }
    violations = []
    linked = []
    for source_record in records:
        article = source_record.article
        payload = source_record.payload or {}
        payload_doi = normalize_doi(payload.get("doi") or "")
        expected_arxiv = normalize_arxiv_id(source_record.external_id)
        if article is None:
            violations.append(
                {
                    "type": "orphan_source_record",
                    "external_id": source_record.external_id,
                }
            )
            continue
        if article.arxiv_id != expected_arxiv:
            violations.append(
                {
                    "type": "canonical_arxiv_mismatch",
                    "external_id": source_record.external_id,
                    "expected": expected_arxiv,
                    "observed": article.arxiv_id,
                }
            )
        if payload_doi and article.doi != payload_doi:
            violations.append(
                {
                    "type": "doi_mismatch",
                    "external_id": source_record.external_id,
                    "expected": payload_doi,
                    "observed": article.doi,
                }
            )
        version = versions.get(source_record.external_id)
        if version is None or version.article_id != article.pk:
            violations.append(
                {
                    "type": "missing_or_misaligned_version",
                    "external_id": source_record.external_id,
                }
            )
        linked.append(
            {
                "external_id": source_record.external_id,
                "canonical_article_id": str(article.pk),
                "arxiv_id": article.arxiv_id,
                "doi": article.doi or "",
                "doi_supplied_by_arxiv": bool(payload_doi),
                "version_number": version.version_number if version else None,
            }
        )

    arxiv_article_ids = {
        str(value)
        for value in Article.objects.exclude(arxiv_id__isnull=True)
        .exclude(arxiv_id="")
        .values_list("pk", flat=True)
    }
    title_year_warnings = []
    # The small scoped corpus makes an explicit grouped pass clearer and auditable.
    groups: dict[tuple[str, int], list[Article]] = {}
    for article in Article.objects.exclude(normalized_title="").exclude(
        year__isnull=True
    ):
        groups.setdefault((article.normalized_title, article.year), []).append(article)
    for (title, year), articles in groups.items():
        if len(articles) < 2 or not any(
            str(article.pk) in arxiv_article_ids for article in articles
        ):
            continue
        title_year_warnings.append(
            {
                "normalized_title": title,
                "year": year,
                "articles": [
                    {
                        "id": str(article.pk),
                        "doi": article.doi or "",
                        "arxiv_id": article.arxiv_id or "",
                    }
                    for article in articles
                ],
            }
        )

    report = {
        "format_version": 1,
        "protocol": "arxiv_canonical_link_audit",
        "acquisition_report": str(args.acquisition_report),
        "acquisition_report_sha256": file_sha256(args.acquisition_report),
        "counts": {
            "arxiv_source_records": len(records),
            "canonical_articles_with_arxiv_id": len(arxiv_article_ids),
            "arxiv_versions": len(versions),
            "doi_linked_records": sum(bool(item["doi"]) for item in linked),
            "doi_supplied_by_arxiv": sum(
                item["doi_supplied_by_arxiv"] for item in linked
            ),
            "arxiv_only_records": sum(not item["doi"] for item in linked),
            "exact_title_year_warning_groups": len(title_year_warnings),
            "violations": len(violations),
        },
        "status": "pass" if not violations else "fail",
        "links": linked,
        "title_year_warnings": title_year_warnings,
        "violations": violations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], **report["counts"]}, indent=2))
    return 2 if args.fail_on_violation and violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
