"""Validate assessor files, measure agreement, and prepare adjudication."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from benchmark.agreement import agreement_report
from benchmark.io import read_judgments
from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, required=True)
    args = parser.parse_args()

    pool_rows = [
        json.loads(line)
        for line in args.pool.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    pool = {
        (str(row["query_id"]), str(row["document_id"])): row for row in pool_rows
    }
    if len(pool) != len(pool_rows):
        raise ValueError("candidate pool contains duplicate query/document pairs")

    judgments = []
    assessor_items = defaultdict(set)
    for path in args.judgments:
        rows = read_judgments(path)
        for judgment in rows:
            key = (judgment.query_id, judgment.document_id)
            if key not in pool:
                raise ValueError(f"{path}: judgment references item outside pool: {key}")
            assessor_items[judgment.assessor_id].add(key)
        judgments.extend(rows)

    expected = set(pool)
    for assessor, items in assessor_items.items():
        if items != expected:
            missing = len(expected - items)
            extra = len(items - expected)
            raise ValueError(
                f"assessor {assessor} coverage mismatch: {missing} missing, {extra} extra"
            )

    report = agreement_report(judgments)
    report.update(
        {
            "pool_sha256": file_sha256(args.pool),
            "judgment_files": [
                {"path": str(path), "sha256": file_sha256(path)}
                for path in args.judgments
            ],
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    labels = defaultdict(dict)
    for judgment in judgments:
        labels[(judgment.query_id, judgment.document_id)][
            judgment.assessor_id
        ] = judgment.relevance
    assessors = sorted(assessor_items)
    fields = [
        "query_id",
        "document_id",
        "query",
        "title",
        *[f"relevance_{assessor}" for assessor in assessors],
        "agreement_status",
        "final_relevance",
        "adjudication_rationale",
    ]
    args.adjudication.parent.mkdir(parents=True, exist_ok=True)
    with args.adjudication.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key in sorted(pool):
            row_labels = labels[key]
            values = list(row_labels.values())
            unanimous = len(set(values)) == 1
            writer.writerow(
                {
                    "query_id": key[0],
                    "document_id": key[1],
                    "query": pool[key]["query"],
                    "title": pool[key]["title"],
                    **{
                        f"relevance_{assessor}": row_labels[assessor]
                        for assessor in assessors
                    },
                    "agreement_status": "unanimous" if unanimous else "conflict",
                    "final_relevance": values[0] if unanimous else "",
                    "adjudication_rationale": "",
                }
            )
    print(
        f"Agreement analyzed: {report['conflict_count']} conflicts across "
        f"{report['unique_item_count']} items"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
