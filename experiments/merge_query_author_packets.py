"""Merge completed author packets while protecting immutable seed-task fields."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


IMMUTABLE_FIELDS = (
    "query_id",
    "task_type",
    "seed_id",
    "seed_title",
    "seed_abstract",
    "seed_publication_date",
    "stratum",
)


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-draft", type=Path, required=True)
    parser.add_argument("--packet-manifest", type=Path, required=True)
    parser.add_argument("--packet", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fields, master_rows = _read(args.master_draft)
    master = {row["query_id"]: row for row in master_rows}
    manifest = json.loads(args.packet_manifest.read_text(encoding="utf-8"))
    expected_author = {
        query_id: author
        for author, packet in manifest["authors"].items()
        for query_id in packet["query_ids"]
    }
    merged = {}
    for path in args.packet:
        packet_fields, rows = _read(path)
        if packet_fields != fields:
            raise ValueError(f"{path}: columns or column order changed")
        for row in rows:
            query_id = row["query_id"]
            if query_id in merged:
                raise ValueError(f"duplicate completed query task: {query_id}")
            if query_id not in master or query_id not in expected_author:
                raise ValueError(f"unknown query task: {query_id}")
            if row["author_id"] != expected_author[query_id]:
                raise ValueError(f"{query_id}: assigned author_id changed")
            for field in IMMUTABLE_FIELDS:
                if row[field] != master[query_id][field]:
                    raise ValueError(f"{query_id}: immutable field changed: {field}")
            merged[query_id] = row
    if set(merged) != set(master):
        missing = sorted(set(master) - set(merged))
        raise ValueError(f"completed packets are missing tasks: {missing[:5]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(merged[row["query_id"]] for row in master_rows)
    print(f"Merged {len(merged)} protected query-author tasks to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
