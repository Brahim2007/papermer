from pathlib import Path

import pytest

from experiments.run_registered_matrix import read_qrel_counts


def test_read_qrel_counts_rejects_missing_identifiers(tmp_path: Path):
    qrels = tmp_path / "qrels.tsv"
    qrels.write_text(
        "query_id\tdocument_id\trelevance\nq1\t\t2\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="invalid qrels row"):
        read_qrel_counts(qrels)


def test_read_qrel_counts_counts_each_judged_candidate(tmp_path: Path):
    qrels = tmp_path / "qrels.tsv"
    qrels.write_text(
        "query_id\tdocument_id\trelevance\n"
        "q1\td1\t2\n"
        "q1\td2\t0\n"
        "q2\td3\t1\n",
        encoding="utf-8",
    )

    assert read_qrel_counts(qrels) == {"q1": 2, "q2": 1}
