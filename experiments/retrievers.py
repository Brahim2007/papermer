from __future__ import annotations

import pandas as pd

from retrieval import (
    BM25Retriever,
    CitationGraphArtifact,
    CitationGraphRetriever,
    CitationHybridRetriever,
    CrossEncoderReranker,
    CrossEncoderRetriever,
    GraphExpansionRetriever,
    HybridRetriever,
    Specter2CorpusCache,
    Specter2Encoder,
    Specter2Retriever,
    StaticMetadataRetriever,
    TfidfRetriever,
)


def build_retriever(
    method: str,
    corpus: pd.DataFrame,
    *,
    batch_size: int = 16,
    specter_cache: Specter2CorpusCache | None = None,
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
    rrf_k: int = 60,
    bm25_weight: float = 1.0,
    specter2_weight: float = 1.0,
    candidate_k: int = 100,
    citation_graph: CitationGraphArtifact | None = None,
    graph_direct_weight: float = 1.0,
    graph_bibliographic_weight: float = 1.0,
    graph_cocitation_weight: float = 1.0,
    graph_rrf_weight: float = 1.0,
    reranker_candidate_k: int = 100,
    reranker_batch_size: int = 8,
    reranker_model: str | None = None,
    reranker_revision: str | None = None,
):
    document_ids = corpus["id"].astype(str).tolist()
    texts = corpus["retrieval_text"].fillna("").astype(str).tolist()
    publication_dates = corpus["_publication_date"].tolist()
    if method == "recency":
        return StaticMetadataRetriever.recency(document_ids, publication_dates)
    if method == "popularity":
        citation_counts = pd.to_numeric(
            corpus["citation_count"], errors="coerce"
        ).fillna(0)
        return StaticMetadataRetriever.popularity(
            document_ids,
            citation_counts.tolist(),
            publication_dates,
        )
    if method == "tfidf":
        return TfidfRetriever().fit(document_ids, texts)

    bm25 = BM25Retriever(k1=bm25_k1, b=bm25_b).fit(document_ids, texts)
    if method == "bm25":
        return bm25

    graph = None
    if method in {"graph", "hybrid_graph", "hybrid_graph_rerank"}:
        if citation_graph is None:
            raise ValueError(f"{method} requires a citation graph artifact")
        graph = CitationGraphRetriever(
            direct_weight=graph_direct_weight,
            bibliographic_weight=graph_bibliographic_weight,
            cocitation_weight=graph_cocitation_weight,
        ).fit(document_ids, citation_graph.edges)
        if method == "graph":
            return GraphExpansionRetriever(bm25, graph)

    titles = corpus["title"].fillna("").astype(str).tolist()
    abstracts = corpus["abstract"].fillna("").astype(str).tolist()
    encoder = Specter2Encoder()
    specter2 = Specter2Retriever(encoder=encoder)
    if specter_cache is not None:
        cached_encoder = specter_cache.metadata.get("encoder", {})
        if cached_encoder != encoder.identity():
            raise ValueError("SPECTER2 cache encoder revisions do not match this run")
        specter2.fit_embeddings(document_ids, specter_cache.subset(document_ids))
    else:
        specter2.fit(document_ids, titles, abstracts, batch_size=batch_size)
    if method == "specter2":
        return specter2

    hybrid = HybridRetriever(
        {"bm25": bm25, "specter2": specter2},
        rrf_k=rrf_k,
        weights={"bm25": bm25_weight, "specter2": specter2_weight},
        candidate_k=candidate_k,
    )
    if method == "hybrid":
        return hybrid
    if method in {"hybrid_graph", "hybrid_graph_rerank"}:
        assert graph is not None
        candidates = CitationHybridRetriever(
            {"bm25": bm25, "specter2": specter2},
            graph,
            rrf_k=rrf_k,
            candidate_k=candidate_k,
            weights={
                "bm25": bm25_weight,
                "specter2": specter2_weight,
                "citation_graph": graph_rrf_weight,
            },
        )
    elif method == "hybrid_rerank":
        candidates = hybrid
    else:
        raise ValueError(f"unsupported retrieval method: {method}")

    if not method.endswith("_rerank"):
        return candidates
    return CrossEncoderRetriever(
        candidates,
        dict(zip(document_ids, texts, strict=True)),
        reranker=CrossEncoderReranker(
            **({"model_name": reranker_model} if reranker_model else {}),
            **({"revision": reranker_revision} if reranker_revision else {}),
        ),
        candidate_k=reranker_candidate_k,
        batch_size=reranker_batch_size,
    )
