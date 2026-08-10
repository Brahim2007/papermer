"""Create a temporally valid, method-blind relevance-assessment pool."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from benchmark.io import read_benchmark_queries
from experiments.build_temporal_benchmark import file_sha256, parse_date
from retrieval import (
    BM25Retriever,
    CitationGraphRetriever,
    CitationHybridRetriever,
    CrossEncoderReranker,
    CrossEncoderRetriever,
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_REVISION,
    GraphExpansionRetriever,
    HybridRetriever,
    Specter2Encoder,
    Specter2Retriever,
    load_citation_graph,
    load_specter2_cache,
    reciprocal_rank_fusion,
)


def _blind_key(seed: int, query_id: str, document_id: str) -> str:
    return hashlib.sha256(
        f"{seed}:{query_id}:{document_id}".encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--specter-cache", type=Path, required=True)
    parser.add_argument("--citation-graph", type=Path)
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=(
            "bm25",
            "specter2",
            "hybrid",
            "graph",
            "hybrid_graph",
            "hybrid_rerank",
            "hybrid_graph_rerank",
            "llm_expanded_hybrid",
        ),
        default=("bm25", "specter2", "hybrid"),
    )
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--graph-rrf-weight", type=float, default=1.0)
    parser.add_argument("--reranker-candidate-k", type=int, default=100)
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--reranker-revision", default=DEFAULT_RERANKER_REVISION)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument(
        "--llm-expansions",
        type=Path,
        help="Frozen JSONL expansions required by llm_expanded_hybrid.",
    )
    parser.add_argument("--assessor", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotation-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.depth < 1 or args.candidate_k < args.depth:
        raise ValueError("candidate-k must be at least depth, and depth must be positive")
    assessors = list(dict.fromkeys(args.assessor))
    if len(assessors) < 2:
        raise ValueError("at least two distinct --assessor values are required")

    corpus_hash = file_sha256(args.corpus)
    corpus = pd.read_csv(args.corpus).fillna("")
    corpus["_publication_date"] = [
        parse_date(str(row.get("publication_date", "")), str(row.get("year", "")))
        for _, row in corpus.iterrows()
    ]
    if corpus["id"].astype(str).duplicated().any():
        raise ValueError("corpus ids must be unique")
    corpus_by_id = {
        str(row["id"]): row for _, row in corpus.iterrows()
    }
    queries = read_benchmark_queries(args.queries)
    expansions = {}
    if args.llm_expansions:
        for line_number, line in enumerate(
            args.llm_expansions.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            query_id = str(row.get("query_id", ""))
            if not query_id or query_id in expansions:
                raise ValueError(f"invalid expansion at line {line_number}")
            if row.get("status") != "expanded" or not str(
                row.get("expanded_query", "")
            ).strip():
                raise ValueError(f"{query_id}: expansion is not successful")
            expansions[query_id] = row
    if "llm_expanded_hybrid" in args.methods:
        if not args.llm_expansions:
            raise ValueError("llm_expanded_hybrid requires --llm-expansions")
        if set(expansions) != {query.query_id for query in queries}:
            raise ValueError("expansion/query ID coverage mismatch")
        for query in queries:
            expected = hashlib.sha256(query.text.encode()).hexdigest()
            if expansions[query.query_id].get("query_sha256") != expected:
                raise ValueError(f"{query.query_id}: expansion was made for another query")
    cache = load_specter2_cache(args.specter_cache)
    if cache.metadata.get("corpus_sha256") != corpus_hash:
        raise ValueError("SPECTER2 cache does not match the corpus snapshot")
    graph_methods = {"graph", "hybrid_graph", "hybrid_graph_rerank"}
    graph_artifact = None
    if args.citation_graph:
        graph_artifact = load_citation_graph(args.citation_graph)
        if graph_artifact.metadata.get("corpus_sha256") != corpus_hash:
            raise ValueError("citation graph does not match the corpus snapshot")
    elif graph_methods.intersection(args.methods):
        raise ValueError("graph methods require --citation-graph")
    reranker = (
        CrossEncoderReranker(
            model_name=args.reranker_model,
            revision=args.reranker_revision,
        )
        if any(method.endswith("_rerank") for method in args.methods)
        else None
    )

    master_rows = []
    grouped: dict[date, list] = defaultdict(list)
    for query in queries:
        grouped[query.query_date].append(query)
        for seed_id in query.seed_ids:
            seed_row = corpus_by_id.get(seed_id)
            if seed_row is None:
                raise ValueError(f"{query.query_id}: unknown seed {seed_id}")
            if seed_row["_publication_date"] > query.query_date:
                raise ValueError(f"{query.query_id}: seed paper is from the future")

    encoder = Specter2Encoder()
    if cache.metadata.get("encoder") != encoder.identity():
        raise ValueError("SPECTER2 cache model revisions do not match this run")
    for query_date in sorted(grouped):
        eligible = corpus[corpus["_publication_date"] <= query_date].copy()
        ids = eligible["id"].astype(str).tolist()
        texts = eligible["retrieval_text"].astype(str).tolist()
        bm25 = BM25Retriever().fit(ids, texts)
        specter2 = Specter2Retriever(encoder).fit_embeddings(
            ids, cache.subset(ids)
        )
        hybrid = HybridRetriever(
            {"bm25": bm25, "specter2": specter2},
            rrf_k=args.rrf_k,
            candidate_k=args.candidate_k,
        )
        retrievers = {"bm25": bm25, "specter2": specter2, "hybrid": hybrid}
        hybrid_graph = None
        if graph_artifact is not None:
            graph_core = CitationGraphRetriever().fit(ids, graph_artifact.edges)
            retrievers["graph"] = GraphExpansionRetriever(bm25, graph_core)
            hybrid_graph = CitationHybridRetriever(
                {"bm25": bm25, "specter2": specter2},
                graph_core,
                rrf_k=args.rrf_k,
                candidate_k=args.candidate_k,
                weights={
                    "bm25": 1.0,
                    "specter2": 1.0,
                    "citation_graph": args.graph_rrf_weight,
                },
            )
            retrievers["hybrid_graph"] = hybrid_graph
        documents = dict(zip(ids, texts, strict=True))
        if "hybrid_rerank" in args.methods:
            retrievers["hybrid_rerank"] = CrossEncoderRetriever(
                hybrid,
                documents,
                reranker=reranker,
                candidate_k=args.reranker_candidate_k,
                batch_size=args.reranker_batch_size,
            )
        if "hybrid_graph_rerank" in args.methods:
            assert hybrid_graph is not None
            retrievers["hybrid_graph_rerank"] = CrossEncoderRetriever(
                hybrid_graph,
                documents,
                reranker=reranker,
                candidate_k=args.reranker_candidate_k,
                batch_size=args.reranker_batch_size,
            )

        for query in grouped[query_date]:
            contributions: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
            for method in args.methods:
                if method == "llm_expanded_hybrid":
                    baseline_results = hybrid.search(
                        query.text,
                        top_k=args.candidate_k,
                        exclude_ids=query.seed_ids,
                    )
                    expanded_results = hybrid.search(
                        expansions[query.query_id]["expanded_query"],
                        top_k=args.candidate_k,
                        exclude_ids=query.seed_ids,
                    )
                    results = reciprocal_rank_fusion(
                        {
                            "baseline": [
                                result.document_id for result in baseline_results
                            ],
                            "llm_expansion": [
                                result.document_id for result in expanded_results
                            ],
                        },
                        rrf_k=args.rrf_k,
                        top_k=args.depth,
                    )
                else:
                    retriever = retrievers[method]
                    if hasattr(retriever, "search_with_seeds"):
                        results = retriever.search_with_seeds(
                            query.text,
                            query.seed_ids,
                            top_k=args.depth,
                            exclude_ids=query.seed_ids,
                        )
                    else:
                        results = retriever.search(
                            query.text,
                            top_k=args.depth,
                            exclude_ids=query.seed_ids,
                        )
                for result in results:
                    contributions[result.document_id][method] = {
                        "rank": result.rank,
                        "score": result.score,
                    }

            ordered_ids = sorted(
                contributions,
                key=lambda document_id: _blind_key(
                    args.seed, query.query_id, document_id
                ),
            )
            for blind_position, document_id in enumerate(ordered_ids, start=1):
                row = corpus_by_id[document_id]
                master_rows.append(
                    {
                        "candidate_id": hashlib.sha256(
                            f"{query.query_id}:{document_id}".encode()
                        ).hexdigest()[:20],
                        "query_id": query.query_id,
                        "query": query.text,
                        "query_date": query.query_date.isoformat(),
                        "task_type": query.task_type,
                        "seed_ids": list(query.seed_ids),
                        "stratum": query.stratum,
                        "document_id": document_id,
                        "title": str(row["title"]),
                        "abstract": str(row["abstract"]),
                        "publication_date": row["_publication_date"].isoformat(),
                        "blind_position": blind_position,
                        "retrieval_evidence": contributions[document_id],
                    }
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in master_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    annotation_fields = [
        "assessor_id",
        "query_id",
        "candidate_id",
        "query",
        "query_date",
        "task_type",
        "seed_ids",
        "document_id",
        "title",
        "abstract",
        "publication_date",
        "assessment_order",
        "relevance",
        "confidence",
        "rationale",
    ]
    args.annotation_dir.mkdir(parents=True, exist_ok=True)
    for assessor in assessors:
        path = args.annotation_dir / f"{assessor}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=annotation_fields)
            writer.writeheader()
            for query in queries:
                assessor_rows = sorted(
                    (
                        row
                        for row in master_rows
                        if row["query_id"] == query.query_id
                    ),
                    key=lambda row: _blind_key(
                        args.seed,
                        f"{assessor}:{query.query_id}",
                        row["document_id"],
                    ),
                )
                for assessment_order, row in enumerate(assessor_rows, start=1):
                    writer.writerow(
                        {
                            key: (
                                "|".join(row[key])
                                if key == "seed_ids"
                                else row.get(key, "")
                            )
                            for key in annotation_fields
                        }
                        | {
                            "assessor_id": assessor,
                            "assessment_order": assessment_order,
                        }
                    )

    manifest = {
        "format_version": 1,
        "protocol": "temporal_method_blind_depth_pool",
        "corpus_sha256": corpus_hash,
        "queries_sha256": file_sha256(args.queries),
        "specter_cache_sha256": file_sha256(args.specter_cache),
        "methods": list(args.methods),
        "depth": args.depth,
        "candidate_k": args.candidate_k,
        "rrf_k": args.rrf_k,
        "graph_rrf_weight": args.graph_rrf_weight,
        "citation_graph_sha256": (
            file_sha256(args.citation_graph) if args.citation_graph else None
        ),
        "reranker": (
            reranker.identity() | {
                "candidate_k": args.reranker_candidate_k,
                "batch_size": args.reranker_batch_size,
            }
            if reranker
            else None
        ),
        "randomization_seed": args.seed,
        "query_count": len(queries),
        "candidate_count": len(master_rows),
        "assessors": assessors,
        "llm_expansions_sha256": (
            file_sha256(args.llm_expansions) if args.llm_expansions else None
        ),
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest["pool_sha256"] = file_sha256(args.output)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(master_rows)} blind candidates for {len(queries)} queries "
        f"and {len(assessors)} assessors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
