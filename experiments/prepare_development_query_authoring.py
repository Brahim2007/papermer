"""Prepare two human-authoring packets for the frozen development split only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--author", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260808)
    args = parser.parse_args()
    authors = list(dict.fromkeys(args.author))
    if len(authors) != 2:
        raise ValueError("exactly two query authors are required")

    split = json.loads(args.split.read_text(encoding="utf-8"))
    development_ids = {
        query_id
        for query_id, partition in split["assignments"].items()
        if partition == "development"
    }
    if len(development_ids) != 20:
        raise ValueError("the frozen split must contain exactly 20 development IDs")

    with args.draft.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        rows = [row for row in reader if row["query_id"] in development_ids]
    if {row["query_id"] for row in rows} != development_ids:
        raise ValueError("development draft rows do not match the frozen split")
    if any(str(row.get("query", "")).strip() for row in rows):
        raise ValueError("source development queries are not blank; refusing to overwrite")

    rows.sort(key=lambda row: row["query_id"])
    buckets = {author: [] for author in authors}
    # Balance exactly 10/10 while retaining a deterministic shuffled order.
    keyed = sorted(
        rows,
        key=lambda item: hashlib.sha256(
            f"{args.seed}:{item['query_id']}".encode()
        ).hexdigest(),
    )
    for index, row in enumerate(keyed):
        author = authors[index % 2]
        prepared = dict(row)
        prepared["author_id"] = author
        prepared["query_date"] = prepared["seed_publication_date"]
        prepared["query"] = ""
        prepared["notes"] = ""
        buckets[author].append(prepared)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    master_rows = sorted(
        [row for author_rows in buckets.values() for row in author_rows],
        key=lambda row: row["query_id"],
    )
    master_path = args.output_dir / "development_authoring_master.csv"
    with master_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(master_rows)

    packet_manifest = {}
    for author, author_rows in buckets.items():
        path = args.output_dir / f"{author}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(author_rows)
        packet_manifest[author] = {
            "path": str(path),
            "query_count": len(author_rows),
            "query_ids": sorted(row["query_id"] for row in author_rows),
            "sha256_before_authoring": file_sha256(path),
        }

    manifest = {
        "format_version": 1,
        "protocol": "human_query_authoring_development_only",
        "randomization_seed": args.seed,
        "source_draft_sha256": file_sha256(args.draft),
        "split_sha256": file_sha256(args.split),
        "development_query_count": len(master_rows),
        "test_rows_exported": 0,
        "editable_fields": ["query", "notes"],
        "master_path": str(master_path),
        "master_sha256": file_sha256(master_path),
        "authors": packet_manifest,
    }
    (args.output_dir / "authoring_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Prepared {len(master_rows)} development tasks: "
        + ", ".join(f"{author}={len(items)}" for author, items in buckets.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
