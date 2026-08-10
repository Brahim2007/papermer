from statistics import mean

import ir_measures
import pytest
from ir_measures import AP, P, R, RR, nDCG

from retrieval.metrics import (
    average_precision,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


QRELS = {
    "graded": {"d1": 3, "d2": 2, "d3": 1, "nonrel": 0},
    "binary": {"r1": 1, "r2": 1, "nonrel": 0},
    "single": {"only": 1, "nonrel": 0},
}
RANKINGS = {
    "graded": ["d3", "d1", "unjudged", "d2", "nonrel"],
    "binary": ["unjudged", "r2", "nonrel", "r1"],
    "single": ["nonrel", "unjudged", "only"],
}


def _run(ranked_ids):
    return {
        document_id: float(len(ranked_ids) - rank)
        for rank, document_id in enumerate(ranked_ids)
    }


@pytest.mark.parametrize("query_id", tuple(QRELS))
def test_per_query_metrics_match_ir_measures_within_one_e_minus_nine(query_id):
    cutoff = 5
    qrels = {query_id: QRELS[query_id]}
    ranking = RANKINGS[query_id]
    reference = ir_measures.calc_aggregate(
        [AP, RR, nDCG @ cutoff, P @ cutoff, R @ cutoff],
        qrels,
        {query_id: _run(ranking)},
    )

    assert average_precision(ranking, qrels[query_id]) == pytest.approx(
        reference[AP], abs=1e-9
    )
    assert reciprocal_rank(ranking, qrels[query_id]) == pytest.approx(
        reference[RR], abs=1e-9
    )
    assert ndcg_at_k(ranking, qrels[query_id], cutoff) == pytest.approx(
        reference[nDCG @ cutoff], abs=1e-9
    )
    assert precision_at_k(ranking, qrels[query_id], cutoff) == pytest.approx(
        reference[P @ cutoff], abs=1e-9
    )
    assert recall_at_k(ranking, qrels[query_id], cutoff) == pytest.approx(
        reference[R @ cutoff], abs=1e-9
    )


def test_mean_metrics_match_trec_aggregate_within_one_e_minus_nine():
    cutoff = 5
    reference = ir_measures.calc_aggregate(
        [AP, RR, nDCG @ cutoff],
        QRELS,
        {query_id: _run(RANKINGS[query_id]) for query_id in QRELS},
    )
    ours = {
        AP: mean(average_precision(RANKINGS[q], QRELS[q]) for q in QRELS),
        RR: mean(reciprocal_rank(RANKINGS[q], QRELS[q]) for q in QRELS),
        nDCG @ cutoff: mean(
            ndcg_at_k(RANKINGS[q], QRELS[q], cutoff) for q in QRELS
        ),
    }
    for measure, value in ours.items():
        assert value == pytest.approx(reference[measure], abs=1e-9)


def test_empty_relevance_and_invalid_cutoffs_are_explicit():
    assert average_precision(["a"], {}) == 0.0
    assert reciprocal_rank(["a"], {}) == 0.0
    assert ndcg_at_k(["a"], {}, 10) == 0.0
    assert recall_at_k(["a"], {}, 10) == 0.0
    with pytest.raises(ValueError, match="at least 1"):
        ndcg_at_k(["a"], {"a": 1}, 0)
    with pytest.raises(ValueError, match="at least 1"):
        recall_at_k(["a"], {"a": 1}, 0)
