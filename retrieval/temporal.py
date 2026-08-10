from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence


class TemporalLeakageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TemporalDocument:
    document_id: str
    publication_date: date


@dataclass(frozen=True, slots=True)
class TemporalQuery:
    query_id: str
    text: str
    query_date: date
    relevant_ids: tuple[str, ...]
    seed_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TemporalSplit:
    train_document_ids: tuple[str, ...]
    evaluation_queries: tuple[TemporalQuery, ...]
    train_end: date
    test_end: date


def build_temporal_split(
    documents: Sequence[TemporalDocument],
    queries: Sequence[TemporalQuery],
    *,
    train_end: date,
    test_end: date,
) -> TemporalSplit:
    if test_end <= train_end:
        raise ValueError("test_end must be later than train_end")
    publication_dates = {
        document.document_id: document.publication_date for document in documents
    }
    if len(publication_dates) != len(documents):
        raise ValueError("document ids must be unique")

    selected_queries = tuple(
        query for query in queries if train_end < query.query_date <= test_end
    )
    for query in selected_queries:
        for document_id in (*query.seed_ids, *query.relevant_ids):
            publication_date = publication_dates.get(document_id)
            if publication_date is None:
                raise TemporalLeakageError(
                    f"{query.query_id} references unknown document {document_id}"
                )
            if publication_date > query.query_date:
                raise TemporalLeakageError(
                    f"{query.query_id} references future document {document_id}: "
                    f"{publication_date} > {query.query_date}"
                )

    train_ids = tuple(
        document.document_id
        for document in documents
        if document.publication_date <= train_end
    )
    return TemporalSplit(
        train_document_ids=train_ids,
        evaluation_queries=selected_queries,
        train_end=train_end,
        test_end=test_end,
    )


def eligible_document_ids(
    publication_dates: Mapping[str, date], *, as_of: date
) -> set[str]:
    return {
        document_id
        for document_id, published in publication_dates.items()
        if published <= as_of
    }
