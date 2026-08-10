"""Compare retrieval runs only when their evaluation contracts match."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


CONTRACT_FIELDS = (
    "protocol",
    "train_end",
    "test_end",
    "corpus_sha256",
    "queries_sha256",
    "qrels_sha256",
    "query_count",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--label",
        default="",
        help="Optional caveat such as 'diagnostic only; not publication qrels'.",
    )
    args = parser.parse_args()

    payloads = [
        json.loads(path.read_text(encoding="utf-8")) for path in args.runs
    ]
    reference = {field: payloads[0].get(field) for field in CONTRACT_FIELDS}
    for path, payload in zip(args.runs[1:], payloads[1:], strict=True):
        observed = {field: payload.get(field) for field in CONTRACT_FIELDS}
        if observed != reference:
            raise ValueError(f"evaluation contract mismatch in {path}")

    metric_names = sorted(
        set().union(*(payload.get("aggregate", {}) for payload in payloads))
    )
    recommendation_metric_names = sorted(
        set().union(
            *(payload.get("recommendation_aggregate", {}) for payload in payloads)
        )
    )
    recommendation_fields = [
        f"recommendation:{metric}" for metric in recommendation_metric_names
    ]
    fields = [
        "method",
        *CONTRACT_FIELDS,
        *metric_names,
        *recommendation_fields,
        "result_path",
        "label",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for path, payload in zip(args.runs, payloads, strict=True):
            writer.writerow(
                {
                    "method": payload["method"],
                    **reference,
                    **payload["aggregate"],
                    **{
                        f"recommendation:{metric}": payload.get(
                            "recommendation_aggregate", {}
                        ).get(metric)
                        for metric in recommendation_metric_names
                    },
                    "result_path": str(path),
                    "label": args.label,
                }
            )
    print(f"Wrote comparable run summary to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
