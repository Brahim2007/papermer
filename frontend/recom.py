"""Django adapters for reproducible production retrieval."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from django.conf import settings
from django.db.models import Count, Max

from api.models import Article
from retrieval import (
    BM25Retriever,
    HybridSearchResult,
    Specter2Retriever,
    TfidfRetriever,
    reciprocal_rank_fusion,
)
from retrieval.specter_cache import load_specter2_cache


logger = logging.getLogger(__name__)
_cache_lock = RLock()
_dense_query_lock = RLock()
_cached_signature: tuple[int, object] | None = None
_cached_retriever: TfidfRetriever | None = None
_live_signature: tuple[int, object] | None = None
_bm25_retriever: BM25Retriever | None = None
_dense_retriever: Specter2Retriever | None = None
_dense_cache_path: str | None = None
_dense_failure: str | None = None


@dataclass(frozen=True, slots=True)
class LiveSearchResponse:
    results: tuple[HybridSearchResult, ...]
    method: str
    components: tuple[str, ...]
    semantic_enabled: bool
    degraded_reason: str | None = None
    component_latencies_ms: dict[str, float] | None = None
    total_latency_ms: float = 0.0


def _corpus_signature() -> tuple[int, object]:
    aggregate = Article.objects.aggregate(count=Count("pk"), latest=Max("add_on"))
    return int(aggregate["count"] or 0), aggregate["latest"]


def _build_retriever() -> TfidfRetriever:
    rows = _corpus_rows()
    if not rows:
        raise ValueError("the article corpus is empty")
    document_ids = [str(row["id"]) for row in rows]
    documents = [
        " ".join(
            value
            for value in (
                row["title"] or "",
                row["abstract"] or "",
                " ".join(row["keywords"] or []),
                row["source"] or "",
                row["type"] or "",
            )
            if value
        )
        for row in rows
    ]
    return TfidfRetriever().fit(document_ids, documents)


def _corpus_rows() -> list[dict]:
    return list(
        Article.objects.order_by("pk").values(
            "id", "title", "abstract", "keywords", "source", "type"
        )
    )


def _retrieval_documents(rows: list[dict]) -> tuple[list[str], list[str]]:
    document_ids = [str(row["id"]) for row in rows]
    documents = [
        " ".join(
            value
            for value in (
                row["title"] or "",
                row["abstract"] or "",
                " ".join(row["keywords"] or []),
                row["source"] or "",
                row["type"] or "",
            )
            if value
        )
        for row in rows
    ]
    return document_ids, documents


def get_retriever() -> TfidfRetriever:
    global _cached_retriever, _cached_signature
    signature = _corpus_signature()
    with _cache_lock:
        if _cached_retriever is None or signature != _cached_signature:
            _cached_retriever = _build_retriever()
            _cached_signature = signature
        return _cached_retriever


def invalidate_retriever_cache() -> None:
    global _cached_retriever, _cached_signature
    global _live_signature, _bm25_retriever, _dense_retriever
    global _dense_cache_path, _dense_failure
    with _cache_lock:
        _cached_retriever = None
        _cached_signature = None
        _live_signature = None
        _bm25_retriever = None
        _dense_retriever = None
        _dense_cache_path = None
        _dense_failure = None


def _build_dense_retriever(document_ids: list[str]) -> Specter2Retriever | None:
    global _dense_cache_path, _dense_failure
    if not settings.SEMANTIC_SEARCH_ENABLED:
        _dense_failure = "disabled"
        return None
    configured = str(settings.SPECTER2_CACHE_PATH or "").strip()
    if not configured:
        _dense_failure = "cache_not_configured"
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = settings.BASE_DIR / path
    if not path.exists() or not path.with_suffix(".json").exists():
        _dense_failure = "cache_unavailable"
        return None
    try:
        cache = load_specter2_cache(path)
        available = set(cache.document_ids)
        covered_ids = [document_id for document_id in document_ids if document_id in available]
        if not covered_ids:
            _dense_failure = "cache_has_no_matching_documents"
            return None
        retriever = Specter2Retriever().fit_embeddings(
            covered_ids, cache.subset(covered_ids)
        )
        _dense_cache_path = str(path)
        _dense_failure = None
        return retriever
    except (FileNotFoundError, ImportError, OSError, ValueError) as exc:
        logger.warning("SPECTER2 live search unavailable: %s", exc)
        _dense_failure = "encoder_or_cache_unavailable"
        return None


def _get_live_retrievers() -> tuple[BM25Retriever, TfidfRetriever, Specter2Retriever | None]:
    global _live_signature, _bm25_retriever, _dense_retriever
    signature = _corpus_signature()
    with _cache_lock:
        if _bm25_retriever is None or signature != _live_signature:
            rows = _corpus_rows()
            if not rows:
                raise ValueError("the article corpus is empty")
            document_ids, documents = _retrieval_documents(rows)
            _bm25_retriever = BM25Retriever().fit(document_ids, documents)
            _dense_retriever = _build_dense_retriever(document_ids)
            _live_signature = signature
        return _bm25_retriever, get_retriever(), _dense_retriever


def live_search(query: str, *, top_k: int = 20, candidate_k: int = 100) -> LiveSearchResponse:
    """Hybrid live retrieval with an explicit, observable dense fallback."""
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= top_k <= 50:
        raise ValueError("top_k must be between 1 and 50")
    total_started = time.perf_counter()
    setup_started = time.perf_counter()
    bm25, tfidf, dense = _get_live_retrievers()
    latencies = {"setup": (time.perf_counter() - setup_started) * 1000}
    component_started = time.perf_counter()
    rankings = {"bm25": bm25.search(query, top_k=candidate_k)}
    latencies["bm25"] = (time.perf_counter() - component_started) * 1000
    component_started = time.perf_counter()
    rankings["tfidf"] = tfidf.search(query, top_k=candidate_k)
    latencies["tfidf"] = (time.perf_counter() - component_started) * 1000
    weights = {"bm25": 1.0, "tfidf": 0.6}
    degraded_reason = _dense_failure
    if dense is not None:
        try:
            # Adapter activation is mutable model state, so dense inference is
            # serialized inside a multi-threaded Gunicorn worker.
            component_started = time.perf_counter()
            with _dense_query_lock:
                rankings["specter2"] = dense.search(query, top_k=candidate_k)
            latencies["specter2"] = (time.perf_counter() - component_started) * 1000
            weights["specter2"] = 1.4
            degraded_reason = None
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("SPECTER2 query failed; using sparse hybrid: %s", exc)
            degraded_reason = "dense_query_failed"
    fusion_started = time.perf_counter()
    fused = reciprocal_rank_fusion(
        rankings, weights=weights, top_k=top_k
    )
    latencies["rrf"] = (time.perf_counter() - fusion_started) * 1000
    components = tuple(rankings)
    semantic_enabled = "specter2" in rankings
    return LiveSearchResponse(
        results=tuple(fused),
        method=(
            "hybrid_specter2_bm25_rrf"
            if semantic_enabled
            else "hybrid_bm25_tfidf_rrf"
        ),
        components=components,
        semantic_enabled=semantic_enabled,
        degraded_reason=degraded_reason,
        component_latencies_ms=latencies,
        total_latency_ms=(time.perf_counter() - total_started) * 1000,
    )


def fuse_search_channels(
    baseline: LiveSearchResponse,
    expanded: LiveSearchResponse,
    *,
    top_k: int,
    expansion_latency_ms: float,
) -> LiveSearchResponse:
    """Fuse baseline and LLM-expanded retrieval as separately named RRF channels."""
    started = time.perf_counter()
    fused = reciprocal_rank_fusion(
        {
            "baseline": [item.document_id for item in baseline.results],
            "llm_expansion": [item.document_id for item in expanded.results],
        },
        top_k=top_k,
    )
    baseline_by_id = {item.document_id: item for item in baseline.results}
    expanded_by_id = {item.document_id: item for item in expanded.results}
    enriched = []
    for item in fused:
        ranks = dict(item.component_ranks)
        if item.document_id in baseline_by_id:
            ranks.update(
                {
                    f"baseline_{name}": rank
                    for name, rank in baseline_by_id[item.document_id].component_ranks.items()
                }
            )
        if item.document_id in expanded_by_id:
            ranks.update(
                {
                    f"expansion_{name}": rank
                    for name, rank in expanded_by_id[item.document_id].component_ranks.items()
                }
            )
        enriched.append(
            HybridSearchResult(item.document_id, item.score, item.rank, ranks)
        )
    fusion_ms = (time.perf_counter() - started) * 1000
    latencies = {
        "llm_expansion": expansion_latency_ms,
        **{
            f"baseline_{key}": value
            for key, value in (baseline.component_latencies_ms or {}).items()
        },
        **{
            f"expansion_{key}": value
            for key, value in (expanded.component_latencies_ms or {}).items()
        },
        "channel_rrf": fusion_ms,
    }
    return LiveSearchResponse(
        results=tuple(enriched),
        method="llm_query_expansion_channel_rrf",
        components=("baseline", "llm_expansion"),
        semantic_enabled=baseline.semantic_enabled or expanded.semantic_enabled,
        degraded_reason=baseline.degraded_reason or expanded.degraded_reason,
        component_latencies_ms=latencies,
        total_latency_ms=(
            baseline.total_latency_ms
            + expansion_latency_ms
            + expanded.total_latency_ms
            + fusion_ms
        ),
    )


def matched_query_terms(query: str, article: Article, *, limit: int = 6) -> list[str]:
    """Return deterministic evidence terms for UI explanations."""
    query_terms = {
        term.casefold()
        for term in re.findall(r"[\w-]{3,}", query, flags=re.UNICODE)
    }
    document_terms = {
        term.casefold()
        for term in re.findall(r"[\w-]{3,}", article.retrieval_text, flags=re.UNICODE)
    }
    return sorted(query_terms & document_terms)[:limit]


def get_similar_items(
    query: str,
    start: int = 0,
    end: int = 50,
    get_scores: bool = False,
    method: str = "tfidf",
):
    """Compatibility API used by existing views.

    Only the measured TF-IDF baseline is enabled in this stage.  Dense and
    hybrid methods will be added as separate experiment configurations rather
    than silently changing the production ranking.
    """
    if method != "tfidf":
        raise ValueError(f"unsupported retrieval method: {method}")
    if start < 0 or end <= start:
        raise ValueError("expected 0 <= start < end")

    results = get_retriever().search(query, top_k=end)[start:end]
    if get_scores:
        return [(result.document_id, result.score) for result in results]
    return [result.document_id for result in results]


def get_explanation(recommended_ids, *, query: str) -> list[dict[str, str]]:
    """Return transparent baseline explanations without generative claims."""
    ids = [
        item[0] if isinstance(item, (tuple, list)) else item
        for item in recommended_ids
    ]
    return [
        {
            "article_id": str(document_id),
            "reason": f"Lexical similarity to the query: {query}",
            "method": "tfidf",
        }
        for document_id in ids
    ]
