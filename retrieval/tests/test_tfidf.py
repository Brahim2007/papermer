import pytest

from retrieval import TfidfRetriever, evaluate_ranking


@pytest.fixture
def retriever():
    return TfidfRetriever().fit(
        ["ir", "vision", "nlp"],
        [
            "hybrid information retrieval with dense sparse ranking",
            "image classification with vision transformers",
            "retrieval augmented language models for scientific papers",
        ],
    )


def test_ranked_results(retriever):
    results = retriever.search("scientific information retrieval", top_k=2)
    assert [result.document_id for result in results] == ["ir", "nlp"]
    assert [result.rank for result in results] == [1, 2]
    assert all(isinstance(result.score, float) for result in results)
    assert results[0].score >= results[1].score


def test_search_can_exclude_seed_document(retriever):
    results = retriever.search(
        "hybrid information retrieval", top_k=3, exclude_ids={"ir", "unknown"}
    )
    assert len(results) == 2
    assert "ir" not in {result.document_id for result in results}


def test_retriever_rejects_invalid_training_data():
    with pytest.raises(ValueError, match="same length"):
        TfidfRetriever().fit(["one"], ["first", "second"])
    with pytest.raises(ValueError, match="empty corpus"):
        TfidfRetriever().fit([], [])
    with pytest.raises(ValueError, match="unique"):
        TfidfRetriever().fit(["same", "same"], ["first", "second"])


def test_evaluate_ranking_known_values():
    metrics = evaluate_ranking(
        ["a", "b", "c", "d"], {"b", "d"}, cutoffs=(2, 4)
    )
    assert metrics["mrr"] == pytest.approx(0.5)
    assert metrics["precision@2"] == pytest.approx(0.5)
    assert metrics["recall@2"] == pytest.approx(0.5)
    assert metrics["recall@4"] == pytest.approx(1.0)
    assert 0.0 < metrics["ndcg@4"] <= 1.0
