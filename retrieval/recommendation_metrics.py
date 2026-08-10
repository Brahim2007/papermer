from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from itertools import combinations
from statistics import median


def topic_diversity_at_k(
    ranked_ids: Sequence[str],
    document_topics: Mapping[str, Sequence[str]],
    k: int,
) -> float:
    """Mean pairwise topic Jaccard distance; unknown-topic pairs are omitted."""
    topic_sets = [
        set(document_topics.get(str(document_id), ()))
        for document_id in ranked_ids[:k]
    ]
    distances = []
    for left, right in combinations(topic_sets, 2):
        if not left or not right:
            continue
        union = left | right
        distances.append(1.0 - len(left & right) / len(union))
    return sum(distances) / len(distances) if distances else 0.0


def citation_novelty_at_k(
    ranked_ids: Sequence[str],
    citation_counts: Mapping[str, int | float],
    k: int,
) -> float:
    """Self-information under a smoothed citation-popularity distribution."""
    smoothed = {
        str(document_id): max(float(count), 0.0) + 1.0
        for document_id, count in citation_counts.items()
    }
    denominator = sum(smoothed.values())
    selected = [
        smoothed[str(document_id)]
        for document_id in ranked_ids[:k]
        if str(document_id) in smoothed
    ]
    if not selected or denominator <= 0:
        return 0.0
    return sum(-math.log2(value / denominator) for value in selected) / len(
        selected
    )


def long_tail_share_at_k(
    ranked_ids: Sequence[str],
    citation_counts: Mapping[str, int | float],
    k: int,
) -> float:
    """Share of results at or below the eligible-corpus median citation count."""
    counts = [max(float(value), 0.0) for value in citation_counts.values()]
    if not counts:
        return 0.0
    threshold = median(counts)
    selected = [
        max(float(citation_counts[str(document_id)]), 0.0)
        for document_id in ranked_ids[:k]
        if str(document_id) in citation_counts
    ]
    return (
        sum(value <= threshold for value in selected) / len(selected)
        if selected
        else 0.0
    )


def mean_age_days_at_k(
    ranked_ids: Sequence[str],
    publication_dates: Mapping[str, date],
    query_date: date,
    k: int,
) -> float:
    ages = [
        (query_date - publication_dates[str(document_id)]).days
        for document_id in ranked_ids[:k]
        if str(document_id) in publication_dates
    ]
    if any(age < 0 for age in ages):
        raise ValueError("future document found in temporally eligible ranking")
    return sum(ages) / len(ages) if ages else 0.0


def catalog_coverage_at_k(
    rankings: Sequence[Sequence[str]],
    catalog_ids: Sequence[str],
    k: int,
) -> float:
    catalog = set(map(str, catalog_ids))
    if not catalog:
        return 0.0
    recommended = {
        str(document_id)
        for ranking in rankings
        for document_id in ranking[:k]
        if str(document_id) in catalog
    }
    return len(recommended) / len(catalog)
