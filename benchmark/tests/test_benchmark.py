from datetime import date

import pandas as pd
import pytest

from benchmark.agreement import agreement_report
from benchmark.schema import BenchmarkQuery, Judgment
from experiments.audit_corpus_quality import audit_corpus
from experiments.freeze_benchmark_split import choose_development_ids
from experiments.run_registered_matrix import build_command
from retrieval.metrics import ndcg_at_k


def test_related_paper_query_requires_seed():
    query = BenchmarkQuery(
        "q1",
        "methods for finding related literature",
        date(2024, 1, 1),
        "related_paper",
    )
    with pytest.raises(ValueError, match="requires seed"):
        query.validate()


def test_agreement_report_exposes_conflicts_and_kappa():
    judgments = [
        Judgment("q1", "a", "r1", 0),
        Judgment("q1", "b", "r1", 1),
        Judgment("q1", "c", "r1", 2),
        Judgment("q1", "a", "r2", 0),
        Judgment("q1", "b", "r2", 2),
        Judgment("q1", "c", "r2", 2),
    ]
    report = agreement_report(judgments)
    assert report["assessor_count"] == 2
    assert report["conflict_count"] == 1
    assert report["pairwise"][0]["exact_agreement"] == pytest.approx(2 / 3)
    assert -1 <= report["krippendorff_alpha_interval"] <= 1


def test_graded_ndcg_rewards_putting_direct_relevance_first():
    grades = {"direct": 2, "partial": 1, "none": 0}
    ideal = ndcg_at_k(["direct", "partial", "none"], grades, 3)
    reversed_ranking = ndcg_at_k(["partial", "direct", "none"], grades, 3)
    assert ideal == pytest.approx(1.0)
    assert reversed_ranking < ideal


def test_frozen_split_is_deterministic_and_balances_popularity():
    rows = [
        {
            "query_id": f"q{index}",
            "stratum": f"year=202{index};popularity={index % 3}",
        }
        for index in range(6)
    ]
    first = choose_development_ids(rows, dev_count=3, seed=7)
    second = choose_development_ids(list(reversed(rows)), dev_count=3, seed=7)
    assert first == second
    assert len(first) == 3
    assert {int(query_id[1:]) % 3 for query_id in first} == {0, 1, 2}


def test_corpus_quality_gate_detects_future_date_and_missing_abstract():
    corpus = pd.DataFrame(
        [
            {
                "id": "paper",
                "title": "A paper",
                "abstract": "",
                "publication_date": "2027-01-01",
                "year": "2027",
                "doi": "10.1/example",
                "citation_count": 0,
                "is_retracted": False,
                "retrieval_text": "A paper",
            }
        ]
    )
    report = audit_corpus(
        corpus,
        as_of_date=date(2026, 8, 4),
        minimum_abstract_rate=0.8,
        minimum_doi_rate=0.5,
        minimum_retrieval_text_rate=0.99,
    )
    assert report["status"] == "fail"
    assert {item["check"] for item in report["violations"]} == {
        "abstract_completeness",
        "future_publication_dates",
        "unexplained_missing_abstracts",
    }


def test_registered_graph_reranker_command_uses_frozen_artifacts(tmp_path):
    spec = {
        "corpus": "corpus.csv",
        "citation_graph": "graph.tsv",
        "specter_cache": "cache.npz",
        "train_end": "2014-12-31",
        "test_end": "2024-12-31",
        "top_k": 100,
    }
    run = {
        "method": "hybrid_graph_rerank",
        "params": {"graph-rrf-weight": 0.25, "reranker-candidate-k": 100},
    }
    command = build_command(
        spec,
        run,
        queries=tmp_path / "queries.jsonl",
        qrels=tmp_path / "qrels.tsv",
        output=tmp_path / "result.json",
    )
    assert "--specter-cache" in command
    assert "--citation-graph" in command
    assert command[command.index("--graph-rrf-weight") + 1] == "0.25"
