import json

import pytest

from experiments.acquire_openalex_citation_closure import load_candidates


def test_load_candidates_enforces_frozen_order(tmp_path):
    path = tmp_path / "candidates.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"rank": 1, "openalex_id": "W1", "distinct_parent_citers": 8}),
                json.dumps({"rank": 2, "openalex_id": "W2", "distinct_parent_citers": 5}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    spec = {"candidate_pool_cap": 10, "min_distinct_parent_citers": 2}

    assert [row["openalex_id"] for row in load_candidates(path, spec)] == ["W1", "W2"]


def test_load_candidates_rejects_rank_gaps(tmp_path):
    path = tmp_path / "candidates.jsonl"
    path.write_text(
        json.dumps({"rank": 2, "openalex_id": "W1", "distinct_parent_citers": 8})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="contiguous"):
        load_candidates(path, {"candidate_pool_cap": 10, "min_distinct_parent_citers": 2})
