import csv

import pytest

from experiments.export_citation_graph import load_document_ids


def test_load_document_ids_without_pandas(tmp_path):
    path = tmp_path / "corpus.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "title"])
        writer.writeheader()
        writer.writerow({"id": "b", "title": "B"})
        writer.writerow({"id": "a", "title": "A"})
    assert load_document_ids(path) == {"a", "b"}


def test_load_document_ids_rejects_duplicates(tmp_path):
    path = tmp_path / "corpus.csv"
    path.write_text("id\na\na\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_document_ids(path)
