"""Create balanced, split-blind query-author packets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--author", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260804)
    args = parser.parse_args()
    authors = list(dict.fromkeys(args.author))
    if len(authors) < 2:
        raise ValueError("at least two distinct query authors are required")

    with args.draft.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        rows = list(reader)
    if "author_id" not in fields:
        raise ValueError("draft has no author_id column")
    groups = defaultdict(list)
    for row in rows:
        groups[row["stratum"]].append(row)
    for group in groups.values():
        group.sort(
            key=lambda row: hashlib.sha256(
                f"{args.seed}:{row['query_id']}".encode()
            ).hexdigest()
        )

    assignments = {author: [] for author in authors}
    author_index = 0
    while any(groups.values()):
        for stratum in sorted(groups):
            if not groups[stratum]:
                continue
            row = groups[stratum].pop(0)
            author = authors[author_index % len(authors)]
            row["author_id"] = author
            assignments[author].append(row)
            author_index += 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    packet_manifest = {}
    for author, packet_rows in assignments.items():
        path = args.output_dir / f"{author}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(packet_rows)
        packet_manifest[author] = {
            "path": str(path),
            "query_count": len(packet_rows),
            "query_ids": [row["query_id"] for row in packet_rows],
            "sha256": file_sha256(path),
        }
    manifest = {
        "protocol": "split_blind_balanced_query_authoring_packets",
        "randomization_seed": args.seed,
        "source_draft_sha256": file_sha256(args.draft),
        "query_count": len(rows),
        "authors": packet_manifest,
        "warning": "do not distribute the frozen development/test split",
    }
    manifest_path = args.output_dir / "authoring_packets_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(rows)} query tasks across {len(authors)} blind author packets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
