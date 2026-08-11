"""Rank external OpenAlex references from a frozen parent corpus."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256
from scholarly.normalize import normalize_openalex_id


PROTOCOL = "citation_closure_candidate_ranking_v1"


def load_parent_membership(path: Path) -> tuple[set[str], set[str]]:
    document_ids: set[str] = set()
    openalex_ids: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "openalex_id"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"parent corpus is missing columns: {sorted(missing)}")
        for row in reader:
            document_id = str(row.get("id") or "").strip()
            if not document_id or document_id in document_ids:
                raise ValueError("parent corpus IDs must be non-empty and unique")
            document_ids.add(document_id)
            raw_openalex = str(row.get("openalex_id") or "").strip()
            if raw_openalex:
                openalex_ids.add(normalize_openalex_id(raw_openalex))
    return document_ids, openalex_ids


def rank_counts(
    counts: list[tuple[str, int]],
    *,
    parent_openalex_ids: set[str],
    minimum: int,
    cap: int,
) -> list[dict]:
    normalized: dict[str, int] = {}
    for identifier, count in counts:
        work_id = normalize_openalex_id(str(identifier))
        if not work_id or work_id in parent_openalex_ids or int(count) < minimum:
            continue
        normalized[work_id] = max(normalized.get(work_id, 0), int(count))
    ranked = sorted(normalized.items(), key=lambda item: (-item[1], item[0]))[:cap]
    return [
        {"rank": rank, "openalex_id": identifier, "distinct_parent_citers": count}
        for rank, (identifier, count) in enumerate(ranked, start=1)
    ]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    corpus_sha256 = file_sha256(args.corpus)
    if corpus_sha256 != spec["parent_corpus_sha256"]:
        raise ValueError("parent corpus checksum differs from the frozen protocol")
    parent_ids, parent_openalex_ids = load_parent_membership(args.corpus)
    if len(parent_ids) != int(spec["parent_document_count"]):
        raise ValueError("parent corpus document count differs from the frozen protocol")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")
    import django

    django.setup()
    from django.db.models import Count

    from api.models import Citation

    parent_edges = Citation.objects.filter(citing_article_id__in=parent_ids)
    edge_count = parent_edges.count()
    resolved_internal = parent_edges.filter(cited_article_id__in=parent_ids).count()
    citing_document_count = (
        parent_edges.values("citing_article_id").distinct().count()
    )
    grouped = list(
        parent_edges.filter(
            cited_article__isnull=True,
            identifier_scheme=spec["selection"]["reference_scheme"],
        )
        .values("cited_identifier")
        .annotate(distinct_parent_citers=Count("citing_article_id", distinct=True))
        .filter(
            distinct_parent_citers__gte=int(spec["min_distinct_parent_citers"])
        )
        .values_list("cited_identifier", "distinct_parent_citers")
    )
    candidates = rank_counts(
        grouped,
        parent_openalex_ids=parent_openalex_ids,
        minimum=int(spec["min_distinct_parent_citers"]),
        cap=int(spec["candidate_pool_cap"]),
    )
    write_jsonl(args.output, candidates)

    distribution = Counter()
    for _, count in grouped:
        for threshold in (2, 3, 5, 10, 20):
            if int(count) >= threshold:
                distribution[str(threshold)] += 1
    report = {
        "format_version": 1,
        "protocol": PROTOCOL,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "spec": {"path": str(args.spec), "sha256": file_sha256(args.spec)},
        "parent_corpus": {
            "path": str(args.corpus),
            "sha256": corpus_sha256,
            "document_count": len(parent_ids),
            "openalex_identifier_count": len(parent_openalex_ids),
        },
        "baseline_graph": {
            "edge_count": edge_count,
            "resolved_internal_edge_count": resolved_internal,
            "internal_edge_rate": resolved_internal / edge_count if edge_count else 0.0,
            "documents_with_outgoing_references": citing_document_count,
            "outgoing_document_coverage": citing_document_count / len(parent_ids),
        },
        "candidate_distribution": dict(sorted(distribution.items(), key=lambda x: int(x[0]))),
        "candidate_count": len(candidates),
        "candidate_file": {"path": str(args.output), "sha256": file_sha256(args.output)},
        "selection": spec["selection"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
