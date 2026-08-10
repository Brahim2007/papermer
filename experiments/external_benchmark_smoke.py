"""Run a deterministic BM25 smoke evaluation on an imported benchmark."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from experiments.build_temporal_benchmark import file_sha256
from retrieval.bm25 import BM25Retriever
from retrieval.metrics import METRIC_DEFINITION_VERSION, evaluate_ranking


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_smoke(benchmark_dir: Path, *, top_k: int = 100) -> dict:
    manifest = json.loads((benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
    corpus = _read_jsonl(benchmark_dir / "corpus.jsonl")
    queries = _read_jsonl(benchmark_dir / "queries.jsonl")
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with (benchmark_dir / "qrels.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            qrels[row["query-id"]][row["corpus-id"]] = int(row["score"])

    retriever = BM25Retriever().fit(
        [item["_id"] for item in corpus],
        [f"{item['title']} {item['text']}".strip() for item in corpus],
    )
    per_query = []
    for query in queries:
        ranked = [
            result.document_id
            for result in retriever.search(query["text"], top_k=top_k)
        ]
        metrics = evaluate_ranking(
            ranked, qrels.get(query["_id"], {}), cutoffs=(5, 10, 20, 100)
        )
        per_query.append({"query_id": query["_id"], **metrics})
    metric_names = sorted(key for key in per_query[0] if key != "query_id")
    aggregate = {
        name: float(np.mean([item[name] for item in per_query]))
        for name in metric_names
    }
    report = {
        "schema_version": 1,
        "purpose": "implementation_smoke_test_not_publication_result",
        "dataset": manifest["dataset"],
        "revision": manifest["revision"],
        "manifest_sha256": file_sha256(benchmark_dir / "manifest.json"),
        "retriever": {"name": "BM25", "k1": 1.2, "b": 0.75, "top_k": top_k},
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "query_count": len(per_query),
        "aggregate": aggregate,
        "per_query": per_query,
    }
    output = benchmark_dir / "bm25_smoke.json"
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=100)
    args = parser.parse_args()
    report = run_smoke(args.benchmark_dir, top_k=args.top_k)
    print(json.dumps(report["aggregate"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
