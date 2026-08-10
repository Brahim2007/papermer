from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from typing import Mapping, Protocol, Sequence

from .tfidf import SearchResult


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    document_id: str
    score: float
    rank: int
    component_ranks: dict[str, int]


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[SearchResult | str]],
    *,
    rrf_k: int = 60,
    weights: Mapping[str, float] | None = None,
    top_k: int | None = None,
) -> list[HybridSearchResult]:
    if rrf_k < 1:
        raise ValueError("rrf_k must be at least 1")
    scores: dict[str, float] = {}
    component_ranks: dict[str, dict[str, int]] = {}
    for component, ranking in rankings.items():
        weight = (weights or {}).get(component, 1.0)
        if weight < 0:
            raise ValueError("RRF weights must be non-negative")
        seen = set()
        for fallback_rank, item in enumerate(ranking, start=1):
            document_id = (
                item.document_id if isinstance(item, SearchResult) else str(item)
            )
            rank = item.rank if isinstance(item, SearchResult) else fallback_rank
            if document_id in seen:
                continue
            seen.add(document_id)
            scores[document_id] = scores.get(document_id, 0.0) + weight / (
                rrf_k + rank
            )
            component_ranks.setdefault(document_id, {})[component] = rank

    ordered = sorted(scores, key=lambda item: (-scores[item], item))
    if top_k is not None:
        ordered = ordered[:top_k]
    return [
        HybridSearchResult(
            document_id=document_id,
            score=scores[document_id],
            rank=rank,
            component_ranks=component_ranks[document_id],
        )
        for rank, document_id in enumerate(ordered, start=1)
    ]


class Retriever(Protocol):
    def search(
        self, query: str, *, top_k: int, exclude_ids: Iterable[str] = ()
    ) -> Sequence[SearchResult]: ...


class HybridRetriever:
    def __init__(
        self,
        retrievers: Mapping[str, Retriever],
        *,
        rrf_k: int = 60,
        weights: Mapping[str, float] | None = None,
        candidate_k: int = 100,
    ) -> None:
        if len(retrievers) < 2:
            raise ValueError("hybrid retrieval requires at least two retrievers")
        self.retrievers = dict(retrievers)
        self.rrf_k = rrf_k
        self.weights = dict(weights or {})
        if candidate_k < 1:
            raise ValueError("candidate_k must be at least 1")
        self.candidate_k = candidate_k

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        candidate_k: int | None = None,
        exclude_ids: Iterable[str] = (),
    ) -> list[HybridSearchResult]:
        candidate_count = candidate_k or self.candidate_k
        rankings = {
            name: retriever.search(
                query, top_k=candidate_count, exclude_ids=exclude_ids
            )
            for name, retriever in self.retrievers.items()
        }
        return reciprocal_rank_fusion(
            rankings,
            rrf_k=self.rrf_k,
            weights=self.weights,
            top_k=top_k,
        )
