"""Export a corpus-aligned citation graph with unresolved reference keys."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


def load_document_ids(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "id" not in set(reader.fieldnames or ()):
            raise ValueError("corpus is missing the id column")
        identifiers = [str(row.get("id") or "").strip() for row in reader]
    if any(not identifier for identifier in identifiers):
        raise ValueError("corpus contains a blank document ID")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("corpus document IDs must be unique")
    return set(identifiers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    document_ids = load_document_ids(args.corpus)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")
    import django

    django.setup()
    from api.models import Citation

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "citing_document_id",
        "cited_reference_key",
        "cited_document_id",
        "source",
    ]
    edge_count = 0
    resolved_count = 0
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        rows = (
            Citation.objects.filter(citing_article_id__in=document_ids)
            .order_by(
                "citing_article_id",
                "identifier_scheme",
                "cited_identifier",
            )
            .values_list(
                "citing_article_id",
                "identifier_scheme",
                "cited_identifier",
                "cited_article_id",
                "source",
            )
        )
        for citing_id, scheme, identifier, cited_id, source in rows:
            resolved_id = (
                str(cited_id)
                if cited_id and str(cited_id) in document_ids and cited_id != citing_id
                else ""
            )
            writer.writerow(
                {
                    "citing_document_id": citing_id,
                    "cited_reference_key": f"{scheme}:{identifier}",
                    "cited_document_id": resolved_id,
                    "source": source,
                }
            )
            edge_count += 1
            resolved_count += bool(resolved_id)

    manifest = {
        "format_version": 1,
        "corpus_sha256": file_sha256(args.corpus),
        "graph_sha256": file_sha256(args.output),
        "document_count": len(document_ids),
        "edge_count": edge_count,
        "resolved_internal_edge_count": resolved_count,
        "unresolved_external_edge_count": edge_count - resolved_count,
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
