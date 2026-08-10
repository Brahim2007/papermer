"""Run the registered B0-B7 retrieval matrix on an imported external benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from experiments.build_temporal_benchmark import file_sha256
from retrieval import (
    BM25Retriever,
    CitationEdge,
    CitationGraphRetriever,
    CitationHybridRetriever,
    CrossEncoderReranker,
    CrossEncoderRetriever,
    GraphExpansionRetriever,
    HybridRetriever,
    Specter2Encoder,
    Specter2Retriever,
    TfidfRetriever,
    evaluate_ranking,
    load_specter2_cache,
)
from retrieval.metrics import METRIC_DEFINITION_VERSION


RUNS = {
    "B0": "TF-IDF",
    "B1": "BM25",
    "B2": "SPECTER2",
    "B3": "BM25 + SPECTER2 / RRF",
    "B4": "citation graph expansion",
    "B5": "BM25 + SPECTER2 + graph / weighted RRF",
    "B6": "B3 candidates + cross-encoder",
    "B7": "B5 candidates + cross-encoder",
}

# Some scientific abstracts exceed Python's conservative 128 KiB CSV default.
csv.field_size_limit(100 * 1024 * 1024)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _read_corpus(benchmark_dir: Path) -> list[dict[str, Any]]:
    """Read the canonical corpus, allowing the equivalent CSV transport form."""
    jsonl_path = benchmark_dir / "corpus.jsonl"
    if jsonl_path.exists():
        return _read_jsonl(jsonl_path)
    with (benchmark_dir / "corpus.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "_id": row["id"],
                    "title": row.get("title", ""),
                    "text": row.get("text", ""),
                    "metadata": json.loads(row.get("metadata_json") or "{}"),
                }
            )
        return rows


def _read_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            qrels[row["query-id"]][row["corpus-id"]] = int(row["score"])
    return dict(qrels)


def citation_edges(corpus: list[dict[str, Any]]) -> tuple[list[CitationEdge], dict]:
    document_ids = {item["_id"] for item in corpus}
    edges = []
    documents_with_edges: set[str] = set()
    internal = 0
    for item in corpus:
        metadata = item.get("metadata") or {}
        references = metadata.get("references", metadata.get("citations", [])) or []
        for raw_reference in references:
            reference = str(raw_reference)
            cited = reference if reference in document_ids else None
            internal += cited is not None
            documents_with_edges.add(item["_id"])
            edges.append(CitationEdge(item["_id"], reference, cited))
    coverage = {
        "edge_count": len(edges),
        "internal_edge_count": internal,
        "internal_edge_rate": internal / len(edges) if edges else 0.0,
        "documents_with_edges": len(documents_with_edges),
        "document_edge_coverage": len(documents_with_edges) / len(corpus),
    }
    return edges, coverage


def _aggregate(per_query: list[dict[str, Any]]) -> dict[str, float]:
    names = [name for name in per_query[0] if name not in {"query_id", "latency_ms"}]
    result = {name: mean(float(row[name]) for row in per_query) for name in names}
    latencies = np.asarray([row["latency_ms"] for row in per_query])
    result.update(
        {
            "latency_mean_ms": float(latencies.mean()),
            "latency_p50_ms": float(np.percentile(latencies, 50)),
            "latency_p95_ms": float(np.percentile(latencies, 95)),
        }
    )
    return result


def _evaluate_run(
    run_id: str,
    retriever: Any,
    queries: list[dict[str, Any]],
    qrels: dict[str, dict[str, int]],
    *,
    top_k: int,
) -> dict[str, Any]:
    per_query = []
    rankings = []
    started = time.perf_counter()
    for query in queries:
        query_started = time.perf_counter()
        results = retriever.search(query["text"], top_k=top_k)
        latency_ms = (time.perf_counter() - query_started) * 1000
        ranked_ids = [item.document_id for item in results]
        per_query.append(
            {
                "query_id": query["_id"],
                "latency_ms": latency_ms,
                **evaluate_ranking(ranked_ids, qrels[query["_id"]]),
            }
        )
        rankings.append({"query_id": query["_id"], "document_ids": ranked_ids})
    return {
        "run_id": run_id,
        "label": RUNS[run_id],
        "status": "completed",
        "query_count": len(queries),
        "top_k": top_k,
        "elapsed_seconds": time.perf_counter() - started,
        "aggregate": _aggregate(per_query),
        "per_query": per_query,
        "rankings": rankings,
    }


def run_matrix(
    benchmark_dir: Path,
    output_dir: Path,
    *,
    specter_cache_path: Path | None = None,
    only: set[str] | None = None,
    top_k: int = 100,
    candidate_k: int = 100,
    reranker_batch_size: int = 16,
    resume: bool = False,
) -> dict[str, Any]:
    unknown = (only or set()) - set(RUNS)
    if unknown:
        raise ValueError(f"unknown run ids: {sorted(unknown)}")
    selected = [run_id for run_id in RUNS if not only or run_id in only]
    corpus = _read_corpus(benchmark_dir)
    queries = _read_jsonl(benchmark_dir / "queries.jsonl")
    qrels = _read_qrels(benchmark_dir / "qrels.tsv")
    manifest = json.loads((benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
    document_ids = [item["_id"] for item in corpus]
    texts = [f"{item.get('title', '')} {item.get('text', '')}".strip() for item in corpus]
    titles = [str(item.get("title") or "") for item in corpus]
    abstracts = [str(item.get("text") or "") for item in corpus]
    documents = dict(zip(document_ids, texts, strict=True))
    edges, graph_coverage = citation_edges(corpus)

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = {
        "schema_version": 1,
        "protocol": "external_full_corpus_B0_B7_v1",
        "dataset": manifest["dataset"],
        "revision": manifest["revision"],
        "benchmark_manifest_sha256": file_sha256(benchmark_dir / "manifest.json"),
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "graph_coverage": graph_coverage,
        "runs": [],
    }
    matrix_path = output_dir / "matrix_manifest.json"
    if resume and matrix_path.exists():
        previous = json.loads(matrix_path.read_text(encoding="utf-8"))
        identity_fields = (
            "protocol",
            "dataset",
            "revision",
            "benchmark_manifest_sha256",
            "metric_definition_version",
            "top_k",
            "candidate_k",
        )
        mismatches = [
            field
            for field in identity_fields
            if previous.get(field) != matrix.get(field)
        ]
        if mismatches:
            raise ValueError(
                f"cannot resume incompatible matrix; mismatched fields: {mismatches}"
            )
        matrix = previous

    bm25 = None
    specter2 = None
    hybrid = None
    graph = None
    tri_hybrid = None

    if any(run_id in selected for run_id in {"B1", "B3", "B4", "B5", "B6", "B7"}):
        bm25 = BM25Retriever().fit(document_ids, texts)
    if any(run_id in selected for run_id in {"B2", "B3", "B5", "B6", "B7"}):
        if specter_cache_path is None:
            for run_id in ("B2", "B3", "B5", "B6", "B7"):
                if run_id in selected:
                    matrix["runs"].append(
                        {
                            "run_id": run_id,
                            "label": RUNS[run_id],
                            "status": "blocked",
                            "reason": "missing pinned SPECTER2 corpus cache",
                        }
                    )
        else:
            cache = load_specter2_cache(specter_cache_path)
            if cache.metadata.get("corpus_sha256") != file_sha256(
                benchmark_dir / "corpus.csv"
            ):
                raise ValueError("SPECTER2 cache corpus hash mismatch")
            encoder = Specter2Encoder()
            if cache.metadata.get("encoder") != encoder.identity():
                raise ValueError("SPECTER2 cache model revision mismatch")
            specter2 = Specter2Retriever(encoder=encoder).fit_embeddings(
                document_ids, cache.subset(document_ids)
            )
            assert bm25 is not None
            hybrid = HybridRetriever(
                {"bm25": bm25, "specter2": specter2},
                candidate_k=candidate_k,
            )

    if any(run_id in selected for run_id in {"B4", "B5", "B7"}) and edges:
        graph = CitationGraphRetriever().fit(document_ids, edges)
        if hybrid is not None and bm25 is not None and specter2 is not None:
            tri_hybrid = CitationHybridRetriever(
                {"bm25": bm25, "specter2": specter2},
                graph,
                candidate_k=candidate_k,
            )

    completed_ids = {entry["run_id"] for entry in matrix["runs"]}
    for run_id in selected:
        if run_id in completed_ids:
            continue
        build_started = time.perf_counter()
        if run_id == "B0":
            retriever = TfidfRetriever().fit(document_ids, texts)
        elif run_id == "B1":
            retriever = bm25
        elif run_id == "B2":
            retriever = specter2
        elif run_id == "B3":
            retriever = hybrid
        elif run_id == "B4":
            if graph is None:
                matrix["runs"].append(
                    {
                        "run_id": run_id,
                        "label": RUNS[run_id],
                        "status": "not_applicable",
                        "reason": "source corpus contains no citation edges",
                    }
                )
                continue
            assert bm25 is not None
            retriever = GraphExpansionRetriever(bm25, graph)
        elif run_id == "B5":
            if tri_hybrid is None:
                matrix["runs"].append(
                    {
                        "run_id": run_id,
                        "label": RUNS[run_id],
                        "status": "not_applicable" if not edges else "blocked",
                        "reason": "citation graph unavailable" if not edges else "SPECTER2 cache unavailable",
                    }
                )
                continue
            retriever = tri_hybrid
        elif run_id in {"B6", "B7"}:
            candidates = hybrid if run_id == "B6" else tri_hybrid
            if candidates is None:
                matrix["runs"].append(
                    {
                        "run_id": run_id,
                        "label": RUNS[run_id],
                        "status": "not_applicable" if not edges and run_id == "B7" else "blocked",
                        "reason": "citation graph unavailable" if not edges and run_id == "B7" else "SPECTER2 cache unavailable",
                    }
                )
                continue
            retriever = CrossEncoderRetriever(
                candidates,
                documents,
                reranker=CrossEncoderReranker(),
                candidate_k=candidate_k,
                batch_size=reranker_batch_size,
            )
        else:  # pragma: no cover
            raise AssertionError(run_id)
        if retriever is None:
            continue
        result = _evaluate_run(run_id, retriever, queries, qrels, top_k=top_k)
        result["index_build_seconds"] = time.perf_counter() - build_started
        result_path = output_dir / f"{run_id}.json"
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        matrix["runs"].append(
            {
                "run_id": run_id,
                "label": RUNS[run_id],
                "status": "completed",
                "result": result_path.name,
                "result_sha256": file_sha256(result_path),
                "aggregate": result["aggregate"],
            }
        )
        matrix_path.write_text(
            json.dumps(matrix, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    matrix["runs"].sort(key=lambda item: item["run_id"])
    matrix["status"] = (
        "completed" if all(item["status"] in {"completed", "not_applicable"} for item in matrix["runs"]) else "partial"
    )
    matrix_path.write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--specter-cache", type=Path)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--candidate-k", type=int, default=100)
    parser.add_argument("--reranker-batch-size", type=int, default=16)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    matrix = run_matrix(
        args.benchmark_dir,
        args.output_dir,
        specter_cache_path=args.specter_cache,
        only=set(args.only),
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        reranker_batch_size=args.reranker_batch_size,
        resume=args.resume,
    )
    print(json.dumps(matrix, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
