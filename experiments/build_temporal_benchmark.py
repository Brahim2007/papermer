"""Build and validate a leak-free temporal retrieval benchmark manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from retrieval.temporal import (
    TemporalDocument,
    TemporalQuery,
    build_temporal_split,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_date(value: str, year: str = "") -> date:
    if value:
        return date.fromisoformat(value)
    if year:
        # Conservative eligibility: an unknown day in a known year is treated
        # as the final day of that year.
        return date(int(float(year)), 12, 31)
    raise ValueError("publication_date or year is required for temporal evaluation")


def read_documents(path: Path) -> list[TemporalDocument]:
    documents = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            documents.append(
                TemporalDocument(
                    document_id=str(row["id"]),
                    publication_date=parse_date(
                        row.get("publication_date", ""), row.get("year", "")
                    ),
                )
            )
    return documents


def read_queries(path: Path) -> list[TemporalQuery]:
    queries = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            try:
                queries.append(
                    TemporalQuery(
                        query_id=str(item["query_id"]),
                        text=item["query"],
                        query_date=date.fromisoformat(item["query_date"]),
                        relevant_ids=tuple(map(str, item["relevant_ids"])),
                        seed_ids=tuple(map(str, item.get("seed_ids", ()))),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid query at line {line_number}: {exc}") from exc
    return queries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--train-end", type=date.fromisoformat, required=True)
    parser.add_argument("--test-end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    documents = read_documents(args.corpus)
    queries = read_queries(args.queries)
    split = build_temporal_split(
        documents,
        queries,
        train_end=args.train_end,
        test_end=args.test_end,
    )
    manifest = {
        "version": 1,
        "protocol": "publication_date_lte_query_date",
        "train_end": split.train_end.isoformat(),
        "test_end": split.test_end.isoformat(),
        "corpus": {
            "path": str(args.corpus),
            "sha256": file_sha256(args.corpus),
            "document_count": len(documents),
            "train_document_count": len(split.train_document_ids),
        },
        "queries": {
            "path": str(args.queries),
            "sha256": file_sha256(args.queries),
            "evaluation_query_count": len(split.evaluation_queries),
            "ids": [query.query_id for query in split.evaluation_queries],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
