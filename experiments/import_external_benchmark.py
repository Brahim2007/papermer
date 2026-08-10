"""Import external IR benchmarks into PaperMetrix's canonical exchange format."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import requests

from experiments.build_temporal_benchmark import file_sha256


BEIR_DATASETS: dict[str, dict[str, str]] = {
    "beir-scifact": {
        "beir_name": "scifact",
        "md5": "5f7d1de60b170fc8027bb7898e2efca1",
        "data_license": "See SciFact upstream license; verify before redistribution",
    },
    "beir-scidocs": {
        "beir_name": "scidocs",
        "md5": "38121350fc3a4d2f48850f6aff52e4a9",
        "data_license": "See SciDocs upstream license; verify before redistribution",
    },
}
BEIR_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{name}.zip"
BEIR_REVISION = "beir-v1.0.0"

LITSEARCH_REPOSITORY = "princeton-nlp/LitSearch"
LITSEARCH_REVISION = "9573fb284a1026c998df47024b888a163f0f0e25"
LITSEARCH_QUERY_FILE = "query/full-00000-of-00001.parquet"
LITSEARCH_CORPUS_FILES = tuple(
    f"corpus_clean/full-{index:05d}-of-00006.parquet" for index in range(6)
)


def _download(url: str, destination: Path) -> Path:
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    with requests.get(url, stream=True, timeout=(15, 120)) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    partial.replace(destination)
    return destination


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.filename}")
        zipped.extractall(destination)


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc


def _normalise_document(item: Mapping[str, Any]) -> dict[str, Any]:
    document_id = str(item.get("_id", item.get("corpusid", ""))).strip()
    if not document_id:
        raise ValueError("document has no identifier")
    title = str(item.get("title") or "").strip()
    text = str(item.get("text", item.get("abstract", "")) or "").strip()
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {"source_metadata": metadata}
    return {
        "_id": document_id,
        "title": title,
        "text": text,
        "metadata": dict(metadata),
    }


def _write_corpus(
    output_dir: Path, documents: Iterable[Mapping[str, Any]]
) -> tuple[int, set[str]]:
    jsonl_path = output_dir / "corpus.jsonl"
    csv_path = output_dir / "corpus.csv"
    count = 0
    identifiers: set[str] = set()
    with (
        jsonl_path.open("w", encoding="utf-8", newline="\n") as jsonl_handle,
        csv_path.open("w", encoding="utf-8", newline="") as csv_handle,
    ):
        writer = csv.DictWriter(
            csv_handle, fieldnames=("id", "title", "text", "metadata_json")
        )
        writer.writeheader()
        for raw in documents:
            document = _normalise_document(raw)
            document_id = document["_id"]
            if document_id in identifiers:
                raise ValueError(f"duplicate document id: {document_id}")
            identifiers.add(document_id)
            metadata_json = json.dumps(
                document["metadata"], ensure_ascii=False, sort_keys=True
            )
            jsonl_handle.write(
                json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n"
            )
            writer.writerow(
                {
                    "id": document_id,
                    "title": document["title"],
                    "text": document["text"],
                    "metadata_json": metadata_json,
                }
            )
            count += 1
    if not count:
        raise ValueError("corpus is empty")
    return count, identifiers


def _write_queries(
    output_dir: Path, queries: Iterable[Mapping[str, Any]]
) -> tuple[int, set[str]]:
    path = output_dir / "queries.jsonl"
    count = 0
    identifiers: set[str] = set()
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in queries:
            query_id = str(item.get("_id", "")).strip()
            text = str(item.get("text", "")).strip()
            if not query_id or not text:
                raise ValueError("query id and text must not be empty")
            if query_id in identifiers:
                raise ValueError(f"duplicate query id: {query_id}")
            identifiers.add(query_id)
            record = {
                "_id": query_id,
                "text": text,
                "metadata": dict(item.get("metadata") or {}),
            }
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    if not count:
        raise ValueError("query set is empty")
    return count, identifiers


def _write_qrels(
    output_dir: Path,
    qrels: Iterable[tuple[str, str, int]],
    *,
    query_ids: set[str],
    document_ids: set[str],
) -> int:
    path = output_dir / "qrels.tsv"
    count = 0
    seen: set[tuple[str, str]] = set()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("query-id", "corpus-id", "score"))
        for query_id, document_id, score in qrels:
            key = (str(query_id), str(document_id))
            if key in seen:
                raise ValueError(f"duplicate qrel: {key}")
            if key[0] not in query_ids:
                raise ValueError(f"qrel refers to unknown query: {key[0]}")
            if key[1] not in document_ids:
                raise ValueError(f"qrel refers to unknown document: {key[1]}")
            if int(score) < 0:
                raise ValueError(f"qrel score must be non-negative: {key}")
            seen.add(key)
            writer.writerow((key[0], key[1], int(score)))
            count += 1
    if not count:
        raise ValueError("qrels are empty")
    return count


def _outputs_manifest(output_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "path": name,
            "bytes": (output_dir / name).stat().st_size,
            "sha256": file_sha256(output_dir / name),
        }
        for name in ("corpus.jsonl", "corpus.csv", "queries.jsonl", "qrels.tsv")
    }


def _write_metadata(
    output_dir: Path,
    *,
    dataset: str,
    revision: str,
    counts: Mapping[str, int],
    sources: list[dict[str, Any]],
    licenses: Mapping[str, Any],
) -> dict[str, Any]:
    license_path = output_dir / "licenses.json"
    license_path.write_text(
        json.dumps(licenses, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "dataset": dataset,
        "revision": revision,
        "task_type": "full_retrieval",
        "counts": dict(counts),
        "sources": sources,
        "outputs": _outputs_manifest(output_dir),
        "licenses": {
            "path": "licenses.json",
            "sha256": file_sha256(license_path),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _beir_qrels(path: Path) -> Iterator[tuple[str, str, int]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            yield row["query-id"], row["corpus-id"], int(row["score"])


def import_beir_archive(
    archive: Path,
    output_dir: Path,
    *,
    dataset: str,
    source_url: str,
    source_md5: str,
) -> dict[str, Any]:
    extracted = archive.parent / f"{archive.stem}-extracted"
    if not extracted.exists():
        _safe_extract(archive, extracted)
    roots = [path.parent for path in extracted.rglob("corpus.jsonl")]
    if len(roots) != 1:
        raise ValueError(f"expected one BEIR corpus in {archive}, found {len(roots)}")
    root = roots[0]
    output_dir.mkdir(parents=True, exist_ok=False)
    documents = _read_jsonl(root / "corpus.jsonl")
    document_count, document_ids = _write_corpus(output_dir, documents)
    qrels_path = root / "qrels" / "test.tsv"
    qrel_records = list(_beir_qrels(qrels_path))
    evaluation_query_ids = {query_id for query_id, _, _ in qrel_records}
    queries = (
        {"_id": item["_id"], "text": item["text"], "metadata": {}}
        for item in _read_jsonl(root / "queries.jsonl")
        if str(item["_id"]) in evaluation_query_ids
    )
    query_count, query_ids = _write_queries(output_dir, queries)
    qrel_count = _write_qrels(
        output_dir,
        qrel_records,
        query_ids=query_ids,
        document_ids=document_ids,
    )
    config = BEIR_DATASETS[dataset]
    return _write_metadata(
        output_dir,
        dataset=dataset,
        revision=BEIR_REVISION,
        counts={"documents": document_count, "queries": query_count, "qrels": qrel_count},
        sources=[
            {
                "url": source_url,
                "bytes": archive.stat().st_size,
                "md5": source_md5,
                "sha256": file_sha256(archive),
            }
        ],
        licenses={
            "code": "Apache-2.0 (BEIR)",
            "data": config["data_license"],
            "redistribute_raw_data": False,
            "note": "BEIR does not grant a uniform license for constituent datasets.",
        },
    )


def _litsearch_documents(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - environment-specific guard
        raise RuntimeError("LitSearch import requires pyarrow") from exc
    for path in paths:
        parquet_file = parquet.ParquetFile(path)
        for batch in parquet_file.iter_batches(
            batch_size=512, columns=("corpusid", "title", "abstract", "citations")
        ):
            for item in batch.to_pylist():
                yield {
                    "_id": str(item["corpusid"]),
                    "title": item.get("title") or "",
                    "text": item.get("abstract") or "",
                    "metadata": {
                        "citations": [str(value) for value in item.get("citations") or []]
                    },
                }


def import_litsearch_files(
    query_path: Path,
    corpus_paths: Iterable[Path],
    output_dir: Path,
    *,
    source_records: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - environment-specific guard
        raise RuntimeError("LitSearch import requires pyarrow") from exc
    corpus_paths = tuple(corpus_paths)
    output_dir.mkdir(parents=True, exist_ok=False)
    document_count, document_ids = _write_corpus(
        output_dir, _litsearch_documents(corpus_paths)
    )
    query_table = parquet.read_table(query_path)
    query_rows = query_table.to_pylist()
    query_records = []
    qrels: list[tuple[str, str, int]] = []
    for index, row in enumerate(query_rows, start=1):
        query_id = f"litsearch-{index:04d}"
        query_records.append(
            {
                "_id": query_id,
                "text": row["query"],
                "metadata": {
                    "query_set": row.get("query_set"),
                    "specificity": row.get("specificity"),
                    "quality": row.get("quality"),
                },
            }
        )
        qrels.extend(
            (query_id, str(document_id), 1) for document_id in row["corpusids"]
        )
    query_count, query_ids = _write_queries(output_dir, query_records)
    qrel_count = _write_qrels(
        output_dir, qrels, query_ids=query_ids, document_ids=document_ids
    )
    return _write_metadata(
        output_dir,
        dataset="litsearch",
        revision=LITSEARCH_REVISION,
        counts={"documents": document_count, "queries": query_count, "qrels": qrel_count},
        sources=source_records,
        licenses={
            "code": "MIT (LitSearch GitHub repository)",
            "data": "Not explicitly declared on the Hugging Face dataset card",
            "redistribute_raw_data": False,
            "note": "Download from the official source; do not commit or redistribute corpus text.",
        },
    )


def _prepare_output(output_root: Path, dataset: str, revision: str) -> Path:
    output_dir = output_root / dataset / revision
    if output_dir.exists():
        raise FileExistsError(
            f"output already exists: {output_dir}; remove it explicitly to rebuild"
        )
    return output_dir


def import_dataset(dataset: str, cache_dir: Path, output_root: Path) -> dict[str, Any]:
    if dataset in BEIR_DATASETS:
        config = BEIR_DATASETS[dataset]
        name = config["beir_name"]
        url = BEIR_URL.format(name=name)
        archive = _download(url, cache_dir / "beir" / f"{name}.zip")
        actual_md5 = _md5(archive)
        if actual_md5 != config["md5"]:
            raise ValueError(
                f"MD5 mismatch for {dataset}: expected {config['md5']}, got {actual_md5}"
            )
        return import_beir_archive(
            archive,
            _prepare_output(output_root, dataset, BEIR_REVISION),
            dataset=dataset,
            source_url=url,
            source_md5=actual_md5,
        )

    if dataset == "litsearch":
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:  # pragma: no cover - environment-specific guard
            raise RuntimeError("LitSearch download requires huggingface-hub") from exc
        base_url = (
            f"https://huggingface.co/datasets/{LITSEARCH_REPOSITORY}/resolve/"
            f"{LITSEARCH_REVISION}"
        )
        paths = (LITSEARCH_QUERY_FILE, *LITSEARCH_CORPUS_FILES)
        downloaded: dict[str, Path] = {}
        sources = []
        for remote_path in paths:
            local_path = Path(
                hf_hub_download(
                    repo_id=LITSEARCH_REPOSITORY,
                    filename=remote_path,
                    repo_type="dataset",
                    revision=LITSEARCH_REVISION,
                    local_dir=cache_dir / "litsearch" / LITSEARCH_REVISION,
                )
            )
            downloaded[remote_path] = local_path
            sources.append(
                {
                    "url": f"{base_url}/{remote_path}",
                    "bytes": local_path.stat().st_size,
                    "sha256": file_sha256(local_path),
                }
            )
        return import_litsearch_files(
            downloaded[LITSEARCH_QUERY_FILE],
            (downloaded[path] for path in LITSEARCH_CORPUS_FILES),
            _prepare_output(output_root, dataset, LITSEARCH_REVISION),
            source_records=sources,
        )
    raise ValueError(f"unsupported dataset: {dataset}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        action="append",
        choices=(*BEIR_DATASETS, "litsearch"),
        required=True,
        help="Repeat to import multiple datasets.",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("artifacts/external_downloads")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/external")
    )
    args = parser.parse_args()
    manifests = []
    for dataset in args.dataset:
        manifest = import_dataset(dataset, args.cache_dir, args.output_root)
        manifests.append(manifest)
        print(
            f"Imported {dataset}: {manifest['counts']['documents']} documents, "
            f"{manifest['counts']['queries']} queries, {manifest['counts']['qrels']} qrels"
        )
    print(json.dumps(manifests, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
