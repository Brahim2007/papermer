"""Evaluate TF-IDF against JSONL queries with explicit relevance judgments.

Query file format, one JSON object per line:
{"query_id": "q1", "query": "...", "relevant_ids": ["paper-a", "paper-b"]}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

import pandas as pd

from retrieval import TfidfRetriever, evaluate_ranking


def read_queries(path: Path) -> list[dict]:
    queries = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            missing = {"query_id", "query", "relevant_ids"} - set(item)
            if missing:
                raise ValueError(f"line {line_number} is missing {sorted(missing)}")
            queries.append(item)
    if not queries:
        raise ValueError("query file is empty")
    return queries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=100)
    args = parser.parse_args()

    corpus = pd.read_csv(args.corpus).fillna("")
    retriever = TfidfRetriever().fit(
        corpus["id"].astype(str).tolist(),
        corpus["retrieval_text"].astype(str).tolist(),
    )

    per_query = []
    for item in read_queries(args.queries):
        ranked_ids = [
            result.document_id
            for result in retriever.search(item["query"], top_k=args.top_k)
        ]
        per_query.append(
            {
                "query_id": item["query_id"],
                **evaluate_ranking(ranked_ids, item["relevant_ids"]),
            }
        )

    metric_names = [key for key in per_query[0] if key != "query_id"]
    aggregate = {
        metric: mean(row[metric] for row in per_query) for metric in metric_names
    }
    result = {
        "method": "tfidf",
        "query_count": len(per_query),
        "corpus_size": retriever.corpus_size,
        "aggregate": aggregate,
        "per_query": per_query,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["aggregate"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
