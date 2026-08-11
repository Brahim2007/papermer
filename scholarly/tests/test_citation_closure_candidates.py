from experiments.build_citation_closure_candidates import rank_counts


def test_rank_counts_is_deterministic_and_excludes_parent_works():
    rows = [("W3", 4), ("https://openalex.org/W2", 4), ("W1", 9), ("W0", 1)]
    ranked = rank_counts(
        rows,
        parent_openalex_ids={"W1"},
        minimum=2,
        cap=2,
    )

    assert ranked == [
        {"rank": 1, "openalex_id": "W2", "distinct_parent_citers": 4},
        {"rank": 2, "openalex_id": "W3", "distinct_parent_citers": 4},
    ]
