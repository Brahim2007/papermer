from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

import numpy as np

from .tfidf import SearchResult


DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_RERANKER_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"
MMARCO_RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MMARCO_RERANKER_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
BGE_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
BGE_RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


class PairScorer(Protocol):
    def predict(self, pairs, **kwargs): ...


class CrossEncoderReranker:
    """Pinned cross-encoder for reranking a bounded candidate set."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_RERANKER_MODEL,
        revision: str = DEFAULT_RERANKER_REVISION,
        device: str | None = None,
        max_length: int = 512,
        scorer: PairScorer | None = None,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.device = device
        self.max_length = max_length
        self._scorer = scorer

    def identity(self) -> dict[str, str | int]:
        return {
            "model": self.model_name,
            "revision": self.revision,
            "max_length": self.max_length,
        }

    def _load(self) -> PairScorer:
        if self._scorer is None:
            from sentence_transformers import CrossEncoder

            self._scorer = CrossEncoder(
                self.model_name,
                revision=self.revision,
                device=self.device,
                max_length=self.max_length,
            )
        return self._scorer

    def rerank(
        self,
        query: str,
        candidates: Sequence[SearchResult],
        documents: Mapping[str, str],
        *,
        top_k: int | None = None,
        batch_size: int = 16,
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not candidates:
            return []
        missing = [
            candidate.document_id
            for candidate in candidates
            if candidate.document_id not in documents
        ]
        if missing:
            raise ValueError(f"missing reranker text for document {missing[0]}")
        pairs = [
            [query, documents[candidate.document_id]] for candidate in candidates
        ]
        scores = np.asarray(
            self._load().predict(
                pairs,
                batch_size=batch_size,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        ).reshape(-1)
        if len(scores) != len(candidates):
            raise ValueError("cross-encoder returned an unexpected score count")
        ranked = sorted(
            zip(candidates, scores, strict=True),
            key=lambda item: (-float(item[1]), item[0].rank, item[0].document_id),
        )
        if top_k is not None:
            ranked = ranked[:top_k]
        return [
            SearchResult(candidate.document_id, float(score), rank)
            for rank, (candidate, score) in enumerate(ranked, start=1)
        ]


class CrossEncoderRetriever:
    def __init__(
        self,
        candidate_retriever,
        documents: Mapping[str, str],
        *,
        reranker: CrossEncoderReranker | None = None,
        candidate_k: int = 100,
        batch_size: int = 16,
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be at least 1")
        self.candidate_retriever = candidate_retriever
        self.documents = dict(documents)
        self.reranker = reranker or CrossEncoderReranker()
        self.candidate_k = candidate_k
        self.batch_size = batch_size

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        candidates = self.candidate_retriever.search(
            query,
            top_k=self.candidate_k,
            exclude_ids=exclude_ids,
        )
        return self.reranker.rerank(
            query,
            candidates,
            self.documents,
            top_k=top_k,
            batch_size=self.batch_size,
        )

    def search_with_seeds(
        self,
        query: str,
        seed_ids: Sequence[str],
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if hasattr(self.candidate_retriever, "search_with_seeds"):
            candidates = self.candidate_retriever.search_with_seeds(
                query,
                seed_ids,
                top_k=self.candidate_k,
                exclude_ids=exclude_ids,
            )
        else:
            candidates = self.candidate_retriever.search(
                query,
                top_k=self.candidate_k,
                exclude_ids=exclude_ids,
            )
        return self.reranker.rerank(
            query,
            candidates,
            self.documents,
            top_k=top_k,
            batch_size=self.batch_size,
        )
