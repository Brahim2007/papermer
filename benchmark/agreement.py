from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from statistics import mean
from typing import Sequence

from sklearn.metrics import cohen_kappa_score

from .schema import Judgment


def _alpha_interval(units: dict[tuple[str, str], list[int]]) -> float:
    observed_pairs = []
    all_values = []
    for values in units.values():
        all_values.extend(values)
        observed_pairs.extend(
            (left - right) ** 2
            for left_index, left in enumerate(values)
            for right_index, right in enumerate(values)
            if left_index != right_index
        )
    if not observed_pairs or len(all_values) < 2:
        return 1.0
    observed = mean(observed_pairs)
    counts = Counter(all_values)
    total = len(all_values)
    expected_sum = sum(
        left_count
        * (right_count - (1 if left == right else 0))
        * (left - right) ** 2
        for left, left_count in counts.items()
        for right, right_count in counts.items()
    )
    expected = expected_sum / (total * (total - 1))
    return 1.0 - observed / expected if expected else 1.0


def agreement_report(judgments: Sequence[Judgment]) -> dict:
    by_assessor: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    units: dict[tuple[str, str], list[int]] = defaultdict(list)
    for judgment in judgments:
        key = (judgment.query_id, judgment.document_id)
        if key in by_assessor[judgment.assessor_id]:
            raise ValueError(f"duplicate judgment for {judgment.assessor_id}: {key}")
        by_assessor[judgment.assessor_id][key] = judgment.relevance
        units[key].append(judgment.relevance)
    if len(by_assessor) < 2:
        raise ValueError("agreement requires at least two assessors")

    pairwise = []
    for left, right in combinations(sorted(by_assessor), 2):
        common = sorted(set(by_assessor[left]) & set(by_assessor[right]))
        if not common:
            raise ValueError(f"assessors {left} and {right} have no common items")
        left_values = [by_assessor[left][key] for key in common]
        right_values = [by_assessor[right][key] for key in common]
        pairwise.append(
            {
                "assessors": [left, right],
                "common_items": len(common),
                "exact_agreement": mean(
                    a == b for a, b in zip(left_values, right_values, strict=True)
                ),
                "cohen_kappa": float(
                    cohen_kappa_score(left_values, right_values)
                ),
                "weighted_kappa_quadratic": float(
                    cohen_kappa_score(
                        left_values, right_values, weights="quadratic"
                    )
                ),
            }
        )

    conflicts = {
        key: values for key, values in units.items() if len(set(values)) > 1
    }
    return {
        "assessor_count": len(by_assessor),
        "unique_item_count": len(units),
        "complete_item_count": sum(
            len(values) == len(by_assessor) for values in units.values()
        ),
        "conflict_count": len(conflicts),
        "krippendorff_alpha_interval": _alpha_interval(units),
        "pairwise": pairwise,
    }
