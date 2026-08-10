"""Build a deliberately leaky fixture to test benchmark orchestration only."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument(
        "--partition", choices=("development", "test"), required=True
    )
    parser.add_argument("--queries-output", type=Path, required=True)
    parser.add_argument("--qrels-output", type=Path, required=True)
    args = parser.parse_args()

    split = json.loads(args.split.read_text(encoding="utf-8"))
    expected = {
        query_id
        for query_id, partition in split["assignments"].items()
        if partition == args.partition
    }
    with args.draft.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["query_id"] in expected
        ]
    if {row["query_id"] for row in rows} != expected:
        raise ValueError("draft does not contain the frozen partition")

    args.queries_output.parent.mkdir(parents=True, exist_ok=True)
    with args.queries_output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    {
                        "query_id": row["query_id"],
                        "query": row["seed_title"],
                        "query_date": row["seed_publication_date"],
                        "task_type": "ad_hoc",
                        "seed_ids": [],
                        "stratum": row["stratum"],
                        "author_id": "diagnostic_title_leakage",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    args.qrels_output.parent.mkdir(parents=True, exist_ok=True)
    with args.qrels_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("query_id", "document_id", "relevance"),
            delimiter="\t",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "query_id": row["query_id"],
                    "document_id": row["seed_id"],
                    "relevance": 2,
                }
            )
    manifest = {
        "protocol": "title_leakage_diagnostic_only",
        "warning": "not human queries; never use in publication tables",
        "partition": args.partition,
        "query_count": len(rows),
        "draft_sha256": file_sha256(args.draft),
        "split_sha256": file_sha256(args.split),
        "queries_sha256": file_sha256(args.queries_output),
        "qrels_sha256": file_sha256(args.qrels_output),
    }
    args.queries_output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(
        f"Wrote {len(rows)} deliberately leaky {args.partition} diagnostic tasks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
