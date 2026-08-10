from datetime import date

import numpy as np
import pytest

from retrieval import (
    BM25Retriever,
    CitationEdge,
    CitationGraphRetriever,
    CrossEncoderReranker,
    SearchResult,
    Specter2Retriever,
    StaticMetadataRetriever,
    catalog_coverage_at_k,
    citation_novelty_at_k,
    long_tail_share_at_k,
    mean_age_days_at_k,
    topic_diversity_at_k,
    load_specter2_cache,
    reciprocal_rank_fusion,
    save_specter2_cache,
)
from retrieval.temporal import (
    TemporalDocument,
    TemporalLeakageError,
    TemporalQuery,
    build_temporal_split,
)


def test_bm25_ranks_matching_document_first():
    retriever = BM25Retriever().fit(
        ["ir", "vision", "biology"],
        [
            "dense sparse scientific information retrieval",
            "vision transformer image classification",
            "protein structure prediction biology",
        ],
    )
    results = retriever.search("scientific retrieval", top_k=2)
    assert results[0].document_id == "ir"
    assert results[0].score > results[1].score


def test_static_metadata_baselines_are_query_independent():
    ids = ["old_popular", "new", "middle"]
    dates = [date(2020, 1, 1), date(2024, 1, 1), date(2022, 1, 1)]
    popularity = StaticMetadataRetriever.popularity(ids, [100, 1, 10], dates)
    recency = StaticMetadataRetriever.recency(ids, dates)
    assert popularity.search("anything", top_k=3)[0].document_id == "old_popular"
    assert recency.search("anything", top_k=3)[0].document_id == "new"
    assert [
        result.document_id
        for result in recency.search(
            "ignored", top_k=3, exclude_ids={"new"}
        )
    ] == ["middle", "old_popular"]


def test_beyond_accuracy_metrics_reward_diversity_and_long_tail():
    ranking = ["rare_a", "rare_b", "popular"]
    topics = {
        "rare_a": ("retrieval",),
        "rare_b": ("graphs",),
        "popular": ("retrieval",),
    }
    citations = {"rare_a": 0, "rare_b": 1, "popular": 100}
    assert topic_diversity_at_k(ranking, topics, 3) == pytest.approx(2 / 3)
    assert long_tail_share_at_k(ranking, citations, 2) == 1.0
    assert citation_novelty_at_k(
        ["rare_a"], citations, 1
    ) > citation_novelty_at_k(["popular"], citations, 1)


def test_age_and_catalog_coverage_respect_cutoff():
    ranking = ["a", "b"]
    ages = mean_age_days_at_k(
        ranking,
        {"a": date(2024, 1, 1), "b": date(2023, 1, 1)},
        date(2024, 1, 11),
        1,
    )
    assert ages == 10
    assert catalog_coverage_at_k([ranking, ["c"]], ["a", "b", "c", "d"], 1) == 0.5


def test_rrf_combines_channels_and_exposes_component_ranks():
    rankings = {
        "bm25": [
            SearchResult("a", 10.0, 1),
            SearchResult("b", 9.0, 2),
        ],
        "specter2": [
            SearchResult("b", 0.9, 1),
            SearchResult("c", 0.8, 2),
        ],
    }
    results = reciprocal_rank_fusion(rankings, rrf_k=60)
    assert results[0].document_id == "b"
    assert results[0].component_ranks == {"bm25": 2, "specter2": 1}
    assert results[0].score == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_channel_weight_can_disable_graph_ablation():
    rankings = {
        "text": [SearchResult("text_winner", 1.0, 1)],
        "citation_graph": [SearchResult("graph_winner", 1.0, 1)],
    }
    results = reciprocal_rank_fusion(
        rankings,
        weights={"text": 1.0, "citation_graph": 0.0},
    )
    assert results[0].document_id == "text_winner"
    assert results[0].score > results[1].score


class FakeScientificEncoder:
    vectors = {
        "retrieval paper": np.array([1.0, 0.0], dtype=np.float32),
        "vision paper": np.array([0.0, 1.0], dtype=np.float32),
        "scientific retrieval": np.array([0.9, 0.1], dtype=np.float32),
    }

    def encode_papers(self, titles, abstracts, *, batch_size=16):
        return np.vstack([self.vectors[title] for title in titles])

    def encode_queries(self, queries, *, batch_size=16):
        return np.vstack([self.vectors[query] for query in queries])


def test_specter_retriever_contract_without_model_download():
    retriever = Specter2Retriever(FakeScientificEncoder()).fit(
        ["ir", "vision"],
        ["retrieval paper", "vision paper"],
        ["", ""],
    )
    results = retriever.search("scientific retrieval", top_k=2)
    assert [result.document_id for result in results] == ["ir", "vision"]


def test_specter_fit_reuses_content_addressed_cache(tmp_path):
    encoder = FakeScientificEncoder()
    first = Specter2Retriever(encoder).fit(
        ["ir", "vision"],
        ["retrieval paper", "vision paper"],
        ["", ""],
        cache_dir=tmp_path,
    )
    second = Specter2Retriever(encoder).fit(
        ["ir", "vision"],
        ["retrieval paper", "vision paper"],
        ["", ""],
        cache_dir=tmp_path,
    )
    assert not first.cache_hit
    assert second.cache_hit
    assert second.cache_key == first.cache_key


def test_corpus_cache_round_trip_and_temporal_subset(tmp_path):
    path = tmp_path / "specter2.npz"
    embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    save_specter2_cache(
        path,
        document_ids=["old", "future"],
        embeddings=embeddings,
        metadata={"corpus_sha256": "fixture", "encoder": {}},
    )
    cache = load_specter2_cache(path)
    assert cache.document_ids == ("old", "future")
    assert np.array_equal(cache.subset(["old"]), embeddings[:1])


def test_citation_graph_uses_direct_and_bibliographic_evidence():
    graph = CitationGraphRetriever().fit(
        ["seed", "coupled", "citer", "other"],
        [
            CitationEdge("seed", "doi:shared"),
            CitationEdge("coupled", "doi:shared"),
            CitationEdge("citer", "doi:seed", "seed"),
            CitationEdge("other", "doi:other"),
        ],
    )
    results = graph.search_from_seeds(["seed"], top_k=3)
    assert {result.document_id for result in results} == {"coupled", "citer"}
    assert all(result.score > 0 for result in results)


class FakePairScorer:
    def predict(self, pairs, **kwargs):
        return np.asarray(
            [2.0 if "best evidence" in document else -1.0 for _, document in pairs]
        )


def test_cross_encoder_reranks_only_supplied_candidates():
    reranker = CrossEncoderReranker(scorer=FakePairScorer())
    candidates = [SearchResult("first", 10.0, 1), SearchResult("best", 1.0, 2)]
    results = reranker.rerank(
        "research query",
        candidates,
        {"first": "weak evidence", "best": "best evidence"},
        top_k=2,
    )
    assert [result.document_id for result in results] == ["best", "first"]
    assert results[0].score == 2.0


def test_temporal_split_rejects_future_relevance():
    documents = [
        TemporalDocument("old", date(2023, 1, 1)),
        TemporalDocument("future", date(2025, 1, 1)),
    ]
    queries = [
        TemporalQuery(
            "q1",
            "retrieval",
            date(2024, 6, 1),
            relevant_ids=("future",),
        )
    ]
    with pytest.raises(TemporalLeakageError, match="future document"):
        build_temporal_split(
            documents,
            queries,
            train_end=date(2023, 12, 31),
            test_end=date(2024, 12, 31),
        )
