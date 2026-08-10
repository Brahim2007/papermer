"""Validate human-authored query tasks and compile canonical JSONL."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from benchmark.schema import BenchmarkQuery
from scholarly.normalize import normalize_title


def token_jaccard(left: str, right: str) -> float:
    left_tokens = set(normalize_title(left).split())
    right_tokens = set(normalize_title(right).split())
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-title-jaccard", type=float, default=0.8)
    args = parser.parse_args()

    compiled = []
    seen = set()
    seen_queries = set()
    with args.draft.open(encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            task_type = str(row.get("task_type", "related_paper")).strip()
            seed_id = str(row.get("seed_id", "")).strip()
            item = {
                "query_id": str(row.get("query_id", "")).strip(),
                "query": str(row.get("query", "")).strip(),
                "query_date": str(row.get("query_date", "")).strip(),
                "task_type": task_type,
                "seed_ids": [seed_id] if seed_id and task_type == "related_paper" else [],
                "stratum": str(row.get("stratum", "")).strip(),
                "author_id": str(row.get("author_id", "")).strip(),
            }
            try:
                query = BenchmarkQuery.from_dict(item)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid draft row {line_number}: {exc}") from exc
            if query.query_id in seen:
                raise ValueError(f"duplicate query_id: {query.query_id}")
            seen.add(query.query_id)
            normalized_query = normalize_title(query.text)
            if normalized_query in seen_queries:
                raise ValueError(f"{query.query_id}: duplicate query text")
            seen_queries.add(normalized_query)
            if not query.author_id:
                raise ValueError(f"{query.query_id}: author_id must not be empty")
            seed_publication_date = str(
                row.get("seed_publication_date", "")
            ).strip()
            if (
                seed_publication_date
                and query.query_date < date.fromisoformat(seed_publication_date)
            ):
                raise ValueError(
                    f"{query.query_id}: query_date precedes seed publication"
                )
            seed_title = str(row.get("seed_title", "")).strip()
            if seed_title and token_jaccard(query.text, seed_title) >= args.max_title_jaccard:
                raise ValueError(
                    f"{query.query_id}: query is too similar to the seed title"
                )
            compiled.append(item)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for item in compiled:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Compiled {len(compiled)} benchmark queries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
