from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from experiments.import_external_benchmark import (
    import_beir_archive,
    import_litsearch_files,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_imports_beir_archive_with_validated_foreign_keys(tmp_path: Path) -> None:
    source = tmp_path / "source" / "scifact"
    _write_jsonl(
        source / "corpus.jsonl",
        [{"_id": "d1", "title": "Alpha", "text": "beta", "metadata": {}}],
    )
    _write_jsonl(
        source / "queries.jsonl",
        [
            {"_id": "q1", "text": "alpha"},
            {"_id": "train-only", "text": "must not be exported"},
        ],
    )
    (source / "qrels").mkdir()
    (source / "qrels" / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq1\td1\t1\n", encoding="utf-8"
    )
    archive = tmp_path / "scifact.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in source.rglob("*"):
            if path.is_file():
                zipped.write(path, path.relative_to(source.parent))

    output = tmp_path / "output"
    manifest = import_beir_archive(
        archive,
        output,
        dataset="beir-scifact",
        source_url="https://example.test/scifact.zip",
        source_md5="fixture",
    )

    assert manifest["counts"] == {"documents": 1, "queries": 1, "qrels": 1}
    assert (output / "corpus.csv").exists()
    assert len(manifest["outputs"]["corpus.jsonl"]["sha256"]) == 64
    assert "train-only" not in (output / "queries.jsonl").read_text(encoding="utf-8")


def test_rejects_dangling_beir_qrel(tmp_path: Path) -> None:
    source = tmp_path / "source" / "scifact"
    _write_jsonl(source / "corpus.jsonl", [{"_id": "d1", "text": "text"}])
    _write_jsonl(source / "queries.jsonl", [{"_id": "q1", "text": "query"}])
    (source / "qrels").mkdir()
    (source / "qrels" / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq1\tmissing\t1\n", encoding="utf-8"
    )
    archive = tmp_path / "scifact.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in source.rglob("*"):
            if path.is_file():
                zipped.write(path, path.relative_to(source.parent))

    with pytest.raises(ValueError, match="unknown document"):
        import_beir_archive(
            archive,
            tmp_path / "output",
            dataset="beir-scifact",
            source_url="fixture",
            source_md5="fixture",
        )


def test_imports_litsearch_parquet(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.parquet"
    query_path = tmp_path / "query.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "corpusid": 7,
                    "title": "Dense retrieval",
                    "abstract": "Scientific search",
                    "citations": [8, 9],
                }
            ]
        ),
        corpus_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "query_set": "author",
                    "query": "papers about scientific search",
                    "specificity": 1,
                    "quality": 2,
                    "corpusids": [7],
                }
            ]
        ),
        query_path,
    )
    output = tmp_path / "output"
    manifest = import_litsearch_files(
        query_path, [corpus_path], output, source_records=[]
    )

    assert manifest["counts"] == {"documents": 1, "queries": 1, "qrels": 1}
    with (output / "qrels.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows == [{"query-id": "litsearch-0001", "corpus-id": "7", "score": "1"}]
