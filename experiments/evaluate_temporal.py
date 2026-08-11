"""Evaluate retrieval without allowing papers published after each query."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

import pandas as pd
import numpy as np

from benchmark.io import read_benchmark_queries
from experiments.build_temporal_benchmark import (
    file_sha256,
    parse_date,
    read_queries,
)
from experiments.retrievers import build_retriever
from retrieval import (
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_REVISION,
    catalog_coverage_at_k,
    citation_novelty_at_k,
    evaluate_ranking,
    long_tail_share_at_k,
    load_citation_graph,
    load_specter2_cache,
    mean_age_days_at_k,
    Specter2Encoder,
    topic_diversity_at_k,
)
from retrieval.metrics import METRIC_DEFINITION_VERSION
from retrieval.temporal import TemporalDocument, build_temporal_split
from retrieval.temporal import TemporalQuery


def read_graded_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels = defaultdict(dict)
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(
            csv.DictReader(handle, delimiter="\t"), start=2
        ):
            query_id = str(row.get("query_id", "")).strip()
            document_id = str(row.get("document_id", "")).strip()
            relevance = int(str(row.get("relevance", "")).strip())
            if not query_id or not document_id or relevance not in {0, 1, 2}:
                raise ValueError(f"invalid qrels row {line_number}")
            if document_id in qrels[query_id]:
                raise ValueError(f"duplicate qrels row {line_number}")
            qrels[query_id][document_id] = relevance
    return dict(qrels)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--method",
        required=True,
        choices=(
            "tfidf",
            "popularity",
            "recency",
            "bm25",
            "specter2",
            "hybrid",
            "graph",
            "hybrid_graph",
            "hybrid_rerank",
            "hybrid_graph_rerank",
        ),
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--train-end", type=date.fromisoformat, required=True)
    parser.add_argument("--test-end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--specter-cache", type=Path)
    parser.add_argument("--bm25-k1", type=float, default=1.2)
    parser.add_argument("--bm25-b", type=float, default=0.75)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--specter2-weight", type=float, default=1.0)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--citation-graph", type=Path)
    parser.add_argument("--graph-direct-weight", type=float, default=1.0)
    parser.add_argument("--graph-bibliographic-weight", type=float, default=1.0)
    parser.add_argument("--graph-cocitation-weight", type=float, default=1.0)
    parser.add_argument("--graph-rrf-weight", type=float, default=1.0)
    parser.add_argument("--reranker-candidate-k", type=int, default=100)
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--reranker-revision", default=DEFAULT_RERANKER_REVISION)
    parser.add_argument("--include-retracted", action="store_true")
    parser.add_argument(
        "--save-rankings",
        action="store_true",
        help="Persist ranked document IDs for audit and error analysis.",
    )
    args = parser.parse_args()

    corpus = pd.read_csv(args.corpus).fillna("")
    specter_cache = None
    if args.specter_cache:
        specter_cache = load_specter2_cache(args.specter_cache)
        expected_hash = specter_cache.metadata.get("corpus_sha256")
        actual_hash = file_sha256(args.corpus)
        if expected_hash != actual_hash:
            raise ValueError("SPECTER2 cache was built from a different corpus snapshot")
    elif args.method in {
        "specter2",
        "hybrid",
        "hybrid_graph",
        "hybrid_rerank",
        "hybrid_graph_rerank",
    }:
        print(
            "Warning: no --specter-cache supplied; each temporal index will be encoded."
        )
    citation_graph = None
    graph_methods = {"graph", "hybrid_graph", "hybrid_graph_rerank"}
    if args.citation_graph:
        citation_graph = load_citation_graph(args.citation_graph)
        if citation_graph.metadata.get("corpus_sha256") != file_sha256(args.corpus):
            raise ValueError("citation graph was built from a different corpus")
    elif args.method in graph_methods:
        raise ValueError(f"{args.method} requires --citation-graph")
    corpus["_publication_date"] = [
        parse_date(str(row.get("publication_date", "")), str(row.get("year", "")))
        for _, row in corpus.iterrows()
    ]
    if not args.include_retracted and "is_retracted" in corpus:
        truthy = {"true", "1", "yes"}
        corpus = corpus[
            ~corpus["is_retracted"].astype(str).str.lower().isin(truthy)
        ].copy()

    graded_qrels = read_graded_qrels(args.qrels) if args.qrels else None
    if graded_qrels is not None:
        benchmark_queries = read_benchmark_queries(args.queries)
        unknown_qrels = set(graded_qrels) - {
            query.query_id for query in benchmark_queries
        }
        if unknown_qrels:
            raise ValueError(f"qrels contain unknown queries: {sorted(unknown_qrels)}")
        queries = []
        for query in benchmark_queries:
            grades = graded_qrels.get(query.query_id, {})
            positives = tuple(
                document_id for document_id, grade in grades.items() if grade > 0
            )
            if not positives:
                raise ValueError(f"{query.query_id} has no positive qrels")
            queries.append(
                TemporalQuery(
                    query.query_id,
                    query.text,
                    query.query_date,
                    positives,
                    query.seed_ids,
                )
            )
    else:
        queries = read_queries(args.queries)
    documents = [
        TemporalDocument(str(row["id"]), row["_publication_date"])
        for _, row in corpus.iterrows()
    ]
    split = build_temporal_split(
        documents, queries, train_end=args.train_end, test_end=args.test_end
    )
    if graded_qrels is not None:
        dates = {document.document_id: document.publication_date for document in documents}
        query_dates = {query.query_id: query.query_date for query in queries}
        for query_id, grades in graded_qrels.items():
            for document_id in grades:
                if document_id not in dates:
                    raise ValueError(f"{query_id} judges unknown document {document_id}")
                if dates[document_id] > query_dates[query_id]:
                    raise ValueError(f"{query_id} judges future document {document_id}")
    grouped = defaultdict(list)
    for query in split.evaluation_queries:
        grouped[query.query_date].append(query)

    dense_methods = {
        "specter2",
        "hybrid",
        "hybrid_graph",
        "hybrid_rerank",
        "hybrid_graph_rerank",
    }
    shared_specter2_encoder = (
        Specter2Encoder() if args.method in dense_methods else None
    )

    started = time.perf_counter()
    per_query = []
    ranked_lists = []
    index_sizes = {}
    index_build_seconds = {}
    for query_date in sorted(grouped):
        eligible = corpus[corpus["_publication_date"] <= query_date]
        index_started = time.perf_counter()
        retriever = build_retriever(
            args.method,
            eligible,
            batch_size=args.batch_size,
            specter_cache=specter_cache,
            specter2_encoder=shared_specter2_encoder,
            bm25_k1=args.bm25_k1,
            bm25_b=args.bm25_b,
            rrf_k=args.rrf_k,
            bm25_weight=args.bm25_weight,
            specter2_weight=args.specter2_weight,
            candidate_k=args.candidate_k,
            citation_graph=citation_graph,
            graph_direct_weight=args.graph_direct_weight,
            graph_bibliographic_weight=args.graph_bibliographic_weight,
            graph_cocitation_weight=args.graph_cocitation_weight,
            graph_rrf_weight=args.graph_rrf_weight,
            reranker_candidate_k=args.reranker_candidate_k,
            reranker_batch_size=args.reranker_batch_size,
            reranker_model=args.reranker_model,
            reranker_revision=args.reranker_revision,
        )
        index_build_seconds[query_date.isoformat()] = (
            time.perf_counter() - index_started
        )
        index_sizes[query_date.isoformat()] = len(eligible)
        eligible_citations = {
            str(row["id"]): float(row["citation_count"] or 0)
            for _, row in eligible.iterrows()
        }
        eligible_dates = {
            str(row["id"]): row["_publication_date"]
            for _, row in eligible.iterrows()
        }
        eligible_topics = {
            str(row["id"]): tuple(
                topic.strip()
                for topic in str(row.get("topics", "")).split("|")
                if topic.strip()
            )
            for _, row in eligible.iterrows()
        }
        for query in grouped[query_date]:
            query_started = time.perf_counter()
            if hasattr(retriever, "search_with_seeds"):
                results = retriever.search_with_seeds(
                    query.text,
                    query.seed_ids,
                    top_k=args.top_k,
                    exclude_ids=query.seed_ids,
                )
            else:
                results = retriever.search(
                    query.text,
                    top_k=args.top_k,
                    exclude_ids=query.seed_ids,
                )
            query_latency_ms = (time.perf_counter() - query_started) * 1000
            ranked_ids = [result.document_id for result in results]
            ranked_lists.append(ranked_ids)
            recommendation_metrics = {}
            for cutoff in (5, 10, 20, 100):
                recommendation_metrics.update(
                    {
                        f"topic_diversity@{cutoff}": topic_diversity_at_k(
                            ranked_ids, eligible_topics, cutoff
                        ),
                        f"citation_novelty@{cutoff}": citation_novelty_at_k(
                            ranked_ids, eligible_citations, cutoff
                        ),
                        f"long_tail_share@{cutoff}": long_tail_share_at_k(
                            ranked_ids, eligible_citations, cutoff
                        ),
                        f"mean_age_days@{cutoff}": mean_age_days_at_k(
                            ranked_ids, eligible_dates, query.query_date, cutoff
                        ),
                    }
                )
            relevance = (
                graded_qrels[query.query_id]
                if graded_qrels is not None
                else query.relevant_ids
            )
            row_result = {
                    "query_id": query.query_id,
                    "query_date": query.query_date.isoformat(),
                    "eligible_document_count": len(eligible),
                    "latency_ms": query_latency_ms,
                    **evaluate_ranking(ranked_ids, relevance),
                    **recommendation_metrics,
                }
            if args.save_rankings:
                row_result["ranked_document_ids"] = ranked_ids
            per_query.append(row_result)

    metric_names = (
        list(
            evaluate_ranking(
                [],
                {},
            )
        )
        if per_query
        else []
    )
    latencies = np.asarray(
        [row["latency_ms"] for row in per_query], dtype=np.float64
    )
    recommendation_metric_names = [
        key
        for key in per_query[0]
        if key.startswith(
            (
                "topic_diversity@",
                "citation_novelty@",
                "long_tail_share@",
                "mean_age_days@",
            )
        )
    ] if per_query else []
    catalog_ids = corpus[
        corpus["_publication_date"]
        <= max((query.query_date for query in split.evaluation_queries), default=args.test_end)
    ]["id"].astype(str).tolist()
    result = {
        "protocol": "publication_date_lte_query_date",
        "method": args.method,
        "metric_definition": {
            "version": METRIC_DEFINITION_VERSION,
            "reference": "ir-measures==0.4.3/pytrec_eval",
            "unjudged_documents": "nonrelevant",
            "binary_relevance_threshold": "grade > 0",
            "ndcg_gain": "linear relevance grade",
        },
        "configuration": {
            "top_k": args.top_k,
            "batch_size": args.batch_size,
            "bm25": {"k1": args.bm25_k1, "b": args.bm25_b},
            "rrf": {
                "k": args.rrf_k,
                "candidate_k": args.candidate_k,
                "weights": {
                    "bm25": args.bm25_weight,
                    "specter2": args.specter2_weight,
                    "citation_graph": args.graph_rrf_weight,
                },
            },
            "include_retracted": args.include_retracted,
            "save_rankings": args.save_rankings,
            "citation_graph": {
                "direct_weight": args.graph_direct_weight,
                "bibliographic_weight": args.graph_bibliographic_weight,
                "cocitation_weight": args.graph_cocitation_weight,
            },
            "reranker": {
                "model": args.reranker_model,
                "revision": args.reranker_revision,
                "candidate_k": args.reranker_candidate_k,
                "batch_size": args.reranker_batch_size,
            },
        },
        "train_end": args.train_end.isoformat(),
        "test_end": args.test_end.isoformat(),
        "corpus_sha256": file_sha256(args.corpus),
        "queries_sha256": file_sha256(args.queries),
        "qrels_sha256": file_sha256(args.qrels) if args.qrels else None,
        "specter_cache": (
            {
                "path": str(args.specter_cache),
                "sha256": file_sha256(args.specter_cache),
                "metadata": specter_cache.metadata,
            }
            if specter_cache and args.specter_cache
            else None
        ),
        "citation_graph": (
            {
                "path": str(args.citation_graph),
                "sha256": file_sha256(args.citation_graph),
                "metadata": citation_graph.metadata,
            }
            if citation_graph and args.citation_graph
            else None
        ),
        "query_count": len(per_query),
        "index_sizes_by_query_date": index_sizes,
        "index_build_seconds_by_query_date": index_build_seconds,
        "elapsed_seconds": time.perf_counter() - started,
        "system_metrics": (
            {
                "query_latency_ms_mean": float(latencies.mean()),
                "query_latency_ms_p50": float(np.percentile(latencies, 50)),
                "query_latency_ms_p95": float(np.percentile(latencies, 95)),
                "query_throughput_qps_sequential": float(
                    1000.0 / latencies.mean()
                )
                if latencies.mean() > 0
                else None,
                "index_build_seconds_total": sum(index_build_seconds.values()),
            }
            if len(latencies)
            else {}
        ),
        "aggregate": {
            metric: mean(row[metric] for row in per_query)
            for metric in metric_names
        },
        "recommendation_aggregate": {
            metric: mean(row[metric] for row in per_query)
            for metric in recommendation_metric_names
        }
        | {
            f"catalog_coverage@{cutoff}": catalog_coverage_at_k(
                ranked_lists, catalog_ids, cutoff
            )
            for cutoff in (5, 10, 20, 100)
        },
        "per_query": per_query,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["aggregate"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
