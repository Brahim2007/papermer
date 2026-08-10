from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


@dataclass(frozen=True, slots=True)
class SearchResult:
    document_id: str
    score: float
    rank: int


class TfidfRetriever:
    """Deterministic TF-IDF baseline for retrieval experiments.

    Fitting and searching are separate operations, so a corpus is never fitted
    inside each query.  This class has no Django dependency and can be used by
    offline evaluation scripts.
    """

    def __init__(
        self,
        *,
        ngram_range: tuple[int, int] = (1, 2),
        min_df: int = 1,
        max_df: float = 1.0,
    ) -> None:
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=ngram_range,
            min_df=min_df,
            max_df=max_df,
            stop_words="english",
            sublinear_tf=True,
            strip_accents="unicode",
            dtype=np.float32,
        )
        self._document_ids: list[str] = []
        self._matrix: csr_matrix | None = None

    @property
    def is_fitted(self) -> bool:
        return self._matrix is not None

    @property
    def corpus_size(self) -> int:
        return len(self._document_ids)

    def fit(
        self, document_ids: Sequence[str], documents: Sequence[str]
    ) -> "TfidfRetriever":
        if len(document_ids) != len(documents):
            raise ValueError("document_ids and documents must have the same length")
        if not documents:
            raise ValueError("cannot fit a retriever on an empty corpus")
        if len(set(map(str, document_ids))) != len(document_ids):
            raise ValueError("document_ids must be unique")

        normalized = [text if text and text.strip() else "[missing text]" for text in documents]
        self._document_ids = [str(document_id) for document_id in document_ids]
        self._matrix = self.vectorizer.fit_transform(normalized).tocsr()
        return self

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if not self.is_fitted or self._matrix is None:
            raise RuntimeError("fit must be called before search")
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        query_vector = self.vectorizer.transform([query])
        scores = linear_kernel(query_vector, self._matrix).ravel()
        excluded = {str(document_id) for document_id in exclude_ids}
        available = sum(
            document_id not in excluded for document_id in self._document_ids
        )
        target_count = min(top_k, available)

        # mergesort is stable, making ties deterministic by corpus order.
        ordered_indices = np.argsort(-scores, kind="mergesort")
        results: list[SearchResult] = []
        for index in ordered_indices:
            document_id = self._document_ids[int(index)]
            if document_id in excluded:
                continue
            results.append(
                SearchResult(
                    document_id=document_id,
                    score=float(scores[int(index)]),
                    rank=len(results) + 1,
                )
            )
            if len(results) == target_count:
                break
        return results
