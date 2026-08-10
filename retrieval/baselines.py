from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from .tfidf import SearchResult


class StaticMetadataRetriever:
    """Query-independent control baseline for popularity or recency bias."""

    def __init__(self, ranking: Sequence[str]) -> None:
        self.ranking = tuple(map(str, ranking))
        if len(set(self.ranking)) != len(self.ranking):
            raise ValueError("static baseline document ids must be unique")

    @classmethod
    def popularity(
        cls,
        document_ids: Sequence[str],
        citation_counts: Sequence[int | float],
        publication_dates: Sequence[date],
    ) -> "StaticMetadataRetriever":
        if not (
            len(document_ids) == len(citation_counts) == len(publication_dates)
        ):
            raise ValueError("popularity metadata lengths must match")
        rows = zip(
            map(str, document_ids),
            map(float, citation_counts),
            publication_dates,
            strict=True,
        )
        return cls(
            [
                document_id
                for document_id, _, _ in sorted(
                    rows,
                    key=lambda row: (-row[1], -row[2].toordinal(), row[0]),
                )
            ]
        )

    @classmethod
    def recency(
        cls,
        document_ids: Sequence[str],
        publication_dates: Sequence[date],
    ) -> "StaticMetadataRetriever":
        if len(document_ids) != len(publication_dates):
            raise ValueError("recency metadata lengths must match")
        rows = zip(map(str, document_ids), publication_dates, strict=True)
        return cls(
            [
                document_id
                for document_id, _ in sorted(
                    rows,
                    key=lambda row: (-row[1].toordinal(), row[0]),
                )
            ]
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        excluded = set(map(str, exclude_ids))
        selected = [
            document_id
            for document_id in self.ranking
            if document_id not in excluded
        ][:top_k]
        return [
            SearchResult(document_id, 1.0 / rank, rank)
            for rank, document_id in enumerate(selected, start=1)
        ]
