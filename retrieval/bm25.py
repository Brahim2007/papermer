from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import CountVectorizer

from .tfidf import SearchResult


class BM25Retriever:
    """Okapi BM25 with deterministic ranking and a scikit-learn tokenizer."""

    def __init__(self, *, k1: float = 1.2, b: float = 0.75) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        self.k1 = k1
        self.b = b
        self.vectorizer = CountVectorizer(
            lowercase=True, strip_accents="unicode", stop_words="english"
        )
        self._document_ids: list[str] = []
        self._matrix: csr_matrix | None = None
        self._idf: np.ndarray | None = None
        self._denominator_norm: np.ndarray | None = None

    @property
    def corpus_size(self) -> int:
        return len(self._document_ids)

    def fit(
        self, document_ids: Sequence[str], documents: Sequence[str]
    ) -> "BM25Retriever":
        if len(document_ids) != len(documents):
            raise ValueError("document_ids and documents must have the same length")
        if not documents:
            raise ValueError("cannot fit a retriever on an empty corpus")
        if len(set(map(str, document_ids))) != len(document_ids):
            raise ValueError("document_ids must be unique")

        normalized = [text if text and text.strip() else "[missing text]" for text in documents]
        matrix = self.vectorizer.fit_transform(normalized).tocsr().astype(np.float32)
        document_frequency = np.asarray((matrix > 0).sum(axis=0)).ravel()
        count = matrix.shape[0]
        self._idf = np.log1p(
            (count - document_frequency + 0.5) / (document_frequency + 0.5)
        ).astype(np.float32)
        lengths = np.asarray(matrix.sum(axis=1)).ravel()
        average_length = float(lengths.mean()) or 1.0
        self._denominator_norm = self.k1 * (
            1.0 - self.b + self.b * lengths / average_length
        )
        self._document_ids = [str(document_id) for document_id in document_ids]
        self._matrix = matrix
        return self

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if self._matrix is None or self._idf is None or self._denominator_norm is None:
            raise RuntimeError("fit must be called before search")
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        query_vector = self.vectorizer.transform([query])
        term_indices = query_vector.indices
        scores = np.zeros(self.corpus_size, dtype=np.float32)
        for term_index in term_indices:
            frequencies = self._matrix[:, term_index].toarray().ravel()
            denominator = frequencies + self._denominator_norm
            scores += self._idf[term_index] * (
                frequencies * (self.k1 + 1.0) / np.maximum(denominator, 1e-12)
            )

        excluded = {str(document_id) for document_id in exclude_ids}
        target = min(
            top_k,
            sum(document_id not in excluded for document_id in self._document_ids),
        )
        results: list[SearchResult] = []
        for index in np.argsort(-scores, kind="mergesort"):
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
            if len(results) == target:
                break
        return results
