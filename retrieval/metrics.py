from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Mapping


RelevanceInput = Iterable[str] | Mapping[str, int | float]
METRIC_DEFINITION_VERSION = "trec-eval-compatible-v2"


def _relevance_mapping(relevance: RelevanceInput) -> dict[str, float]:
    if isinstance(relevance, Mapping):
        return {
            str(document_id): float(grade)
            for document_id, grade in relevance.items()
        }
    return {str(document_id): 1.0 for document_id in relevance}


def recall_at_k(
    ranked_ids: Sequence[str], relevant_ids: RelevanceInput, k: int
) -> float:
    if k < 1:
        raise ValueError("k must be at least 1")
    relevant = {
        document_id
        for document_id, grade in _relevance_mapping(relevant_ids).items()
        if grade > 0
    }
    if not relevant:
        return 0.0
    retrieved = {str(document_id) for document_id in ranked_ids[:k]}
    return len(retrieved & relevant) / len(relevant)


def precision_at_k(
    ranked_ids: Sequence[str], relevant_ids: RelevanceInput, k: int
) -> float:
    if k < 1:
        raise ValueError("k must be at least 1")
    relevant = {
        document_id
        for document_id, grade in _relevance_mapping(relevant_ids).items()
        if grade > 0
    }
    retrieved = [str(document_id) for document_id in ranked_ids[:k]]
    return sum(document_id in relevant for document_id in retrieved) / k


def reciprocal_rank(ranked_ids: Sequence[str], relevant_ids: RelevanceInput) -> float:
    relevant = {
        document_id
        for document_id, grade in _relevance_mapping(relevant_ids).items()
        if grade > 0
    }
    for rank, document_id in enumerate(ranked_ids, start=1):
        if str(document_id) in relevant:
            return 1.0 / rank
    return 0.0


def average_precision(
    ranked_ids: Sequence[str], relevant_ids: RelevanceInput
) -> float:
    """TREC AP for one query; averaging this value across queries yields MAP."""
    relevant = {
        document_id
        for document_id, grade in _relevance_mapping(relevant_ids).items()
        if grade > 0
    }
    if not relevant:
        return 0.0
    hits = 0
    precision_sum = 0.0
    seen: set[str] = set()
    for rank, raw_document_id in enumerate(ranked_ids, start=1):
        document_id = str(raw_document_id)
        if document_id in seen:
            continue
        seen.add(document_id)
        if document_id in relevant:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / len(relevant)


def ndcg_at_k(
    ranked_ids: Sequence[str], relevant_ids: RelevanceInput, k: int
) -> float:
    if k < 1:
        raise ValueError("k must be at least 1")
    relevance = _relevance_mapping(relevant_ids)
    positive_grades = [grade for grade in relevance.values() if grade > 0]
    if not positive_grades:
        return 0.0
    dcg = sum(
        relevance.get(str(document_id), 0.0) / math.log2(rank + 1)
        for rank, document_id in enumerate(ranked_ids[:k], start=1)
        if relevance.get(str(document_id), 0.0) > 0
    )
    ideal = sorted(positive_grades, reverse=True)[:k]
    idcg = sum(
        grade / math.log2(rank + 1)
        for rank, grade in enumerate(ideal, start=1)
    )
    return dcg / idcg if idcg else 0.0


def evaluate_ranking(
    ranked_ids: Sequence[str],
    relevant_ids: RelevanceInput,
    *,
    cutoffs: Sequence[int] = (5, 10, 20, 100),
) -> dict[str, float]:
    relevant = (
        dict(relevant_ids)
        if isinstance(relevant_ids, Mapping)
        else list(relevant_ids)
    )
    metrics: dict[str, float] = {
        "map": average_precision(ranked_ids, relevant),
        "mrr": reciprocal_rank(ranked_ids, relevant),
    }
    for k in cutoffs:
        metrics[f"precision@{k}"] = precision_at_k(ranked_ids, relevant, k)
        metrics[f"recall@{k}"] = recall_at_k(ranked_ids, relevant, k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(ranked_ids, relevant, k)
    return metrics
