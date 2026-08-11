"""Create a deterministic, popularity-neutral OpenAlex subset for bulk import."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from scholarly.snapshot import (
    deterministic_sample,
    file_sha256,
    iter_jsonl,
    validate_bulk_scope,
)


def rows(paths: list[Path]) -> Iterator[dict]:
    for path in paths:
        for _, payload in iter_jsonl(path):
            yield payload


def write_deterministic_gzip(path: Path, selected: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            for item in selected:
                line = json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                zipped.write(line.encode("utf-8") + b"\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    inputs = [path.resolve() for path in args.input]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        parser.error(f"snapshot input not found: {missing}")
    spec_raw = args.spec.read_bytes()
    spec = json.loads(spec_raw)
    validate_bulk_scope(spec)
    selected, rejections = deterministic_sample(rows(inputs), spec=spec)
    target = int(spec["target_document_count"])
    if len(selected) != target:
        parser.error(f"eligible input produced {len(selected)} records; need {target}")

    write_deterministic_gzip(args.output, selected)
    manifest = {
        "protocol": "openalex_deterministic_bottom_k_selection_v1",
        "spec_path": str(args.spec),
        "spec_sha256": hashlib.sha256(spec_raw).hexdigest(),
        "inputs": {str(path): file_sha256(path) for path in inputs},
        "output": str(args.output),
        "output_sha256": file_sha256(args.output),
        "document_count": len(selected),
        "rejections": dict(sorted(rejections.items())),
        "sampling": spec["sampling"],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.manifest.with_suffix(args.manifest.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(args.manifest)
    print(json.dumps({"document_count": len(selected)}))


if __name__ == "__main__":
    main()
