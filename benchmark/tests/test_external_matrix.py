from pathlib import Path

import csv

from experiments.run_external_matrix import _read_corpus, citation_edges


def test_extracts_internal_external_citation_edges() -> None:
    corpus = [
        {"_id": "a", "metadata": {"citations": ["b", "outside"]}},
        {"_id": "b", "metadata": {}},
    ]
    edges, coverage = citation_edges(corpus)
    assert len(edges) == 2
    assert edges[0].cited_document_id == "b"
    assert edges[1].cited_document_id is None
    assert coverage["internal_edge_count"] == 1
    assert coverage["document_edge_coverage"] == 0.5


def test_reads_large_corpus_csv_field(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.csv"
    large_abstract = "a" * (200 * 1024)
    with corpus_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["id", "title", "text", "metadata_json"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "doc-1",
                "title": "Large abstract",
                "text": large_abstract,
                "metadata_json": "{}",
            }
        )

    corpus = _read_corpus(tmp_path)

    assert corpus[0]["_id"] == "doc-1"
    assert corpus[0]["text"] == large_abstract
