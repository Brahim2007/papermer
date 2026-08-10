"""Apply a frozen query-ID split to completed canonical benchmark queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.io import read_benchmark_queries
from experiments.build_temporal_benchmark import file_sha256
from experiments.freeze_benchmark_split import task_contract_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--development-output", type=Path, required=True)
    parser.add_argument("--test-output", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    args = parser.parse_args()

    queries = read_benchmark_queries(args.queries)
    split = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    assignments = split.get("assignments", {})
    query_ids = {query.query_id for query in queries}
    if query_ids != set(assignments):
        missing = sorted(set(assignments) - query_ids)
        extra = sorted(query_ids - set(assignments))
        raise ValueError(
            f"frozen split/query mismatch; missing={missing[:3]}, extra={extra[:3]}"
        )
    contract_rows = [
        {
            "query_id": query.query_id,
            "task_type": query.task_type,
            "seed_id": query.seed_ids[0] if query.seed_ids else "",
            "stratum": query.stratum,
        }
        for query in queries
    ]
    observed_contract = task_contract_hash(contract_rows)
    if observed_contract != split.get("query_task_contract_sha256"):
        raise ValueError("query task identities changed after the split was frozen")

    outputs = {
        "development": args.development_output,
        "test": args.test_output,
    }
    for partition, output in outputs.items():
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            for query in queries:
                if assignments[query.query_id] != partition:
                    continue
                payload = {
                    "query_id": query.query_id,
                    "query": query.text,
                    "query_date": query.query_date.isoformat(),
                    "task_type": query.task_type,
                    "seed_ids": list(query.seed_ids),
                    "stratum": query.stratum,
                    "author_id": query.author_id,
                }
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    frozen = {
        **split,
        "source_queries_sha256": file_sha256(args.queries),
        "split_manifest_sha256": file_sha256(args.split_manifest),
        "development_queries_sha256": file_sha256(args.development_output),
        "test_queries_sha256": file_sha256(args.test_output),
    }
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print(
        f"Materialized {split['development_count']} development and "
        f"{split['test_count']} test queries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
