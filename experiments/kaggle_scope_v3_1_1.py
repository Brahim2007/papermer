"""Kaggle GPU job for the hash-locked Scope v3.1.1 SPECTER2 cache."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


CORPUS_SHA256 = "2d80460bd329c2c5401478320f3dbd1e6d35806631ce4df1e5d96fa280af765f"
DOCUMENT_COUNT = 52493
SPECTER2_BASE_REVISION = "3447645e1def9117997203454fa4495937bfbd83"
SPECTER2_PROXIMITY_REVISION = "2081559630a80fc5851d8f798a05ba81e9468089"
SPECTER2_QUERY_REVISION = "3f4448817028388648a74349ece07af4518ec5bd"
OUTPUT = Path("/kaggle/working/specter2.npz")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_corpus() -> Path:
    candidates = sorted(Path("/kaggle/input").rglob("corpus.csv"))
    for path in candidates:
        if file_sha256(path) == CORPUS_SHA256:
            return path
    observed = {str(path): file_sha256(path) for path in candidates}
    raise RuntimeError(f"frozen corpus not found; observed={observed}")


def main() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "transformers==4.57.6",
            "adapters==1.3.0",
        ],
        check=True,
    )
    import adapters
    import numpy as np
    import pandas as pd
    import torch
    import torch.nn.functional as functional
    import transformers
    from adapters import AutoAdapterModel
    from transformers import AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("Kaggle allocated no CUDA GPU")
    corpus_path = find_corpus()
    corpus = pd.read_csv(corpus_path).fillna("")
    if len(corpus) != DOCUMENT_COUNT:
        raise ValueError(f"unexpected document count: {len(corpus)}")
    ids = corpus["id"].astype(str).tolist()
    if len(set(ids)) != len(ids):
        raise ValueError("corpus IDs must be unique")

    tokenizer = AutoTokenizer.from_pretrained(
        "allenai/specter2_base", revision=SPECTER2_BASE_REVISION
    )
    model = AutoAdapterModel.from_pretrained(
        "allenai/specter2_base", revision=SPECTER2_BASE_REVISION
    )
    model.load_adapter(
        "allenai/specter2",
        source="hf",
        load_as="proximity",
        revision=SPECTER2_PROXIMITY_REVISION,
    )
    model.load_adapter(
        "allenai/specter2_adhoc_query",
        source="hf",
        load_as="adhoc_query",
        revision=SPECTER2_QUERY_REVISION,
    )
    model.set_active_adapters("proximity")
    model.to("cuda").eval()
    separator = tokenizer.sep_token or " [SEP] "
    texts = [
        f"{title}{separator}{abstract}"
        for title, abstract in zip(
            corpus["title"].astype(str),
            corpus["abstract"].astype(str),
            strict=True,
        )
    ]

    batch_size = 64
    batches: list[np.ndarray] = []
    started = time.perf_counter()
    for start in range(0, len(texts), batch_size):
        encoded = tokenizer(
            texts[start : start + batch_size],
            padding=True,
            truncation=True,
            return_tensors="pt",
            return_token_type_ids=False,
            max_length=512,
        )
        encoded = {key: value.to("cuda") for key, value in encoded.items()}
        with torch.inference_mode():
            output = model(**encoded)
            embedding = functional.normalize(
                output.last_hidden_state[:, 0, :], p=2, dim=1
            )
        batches.append(embedding.cpu().numpy().astype(np.float32))
        if start == 0 or (start // batch_size + 1) % 100 == 0:
            print(f"encoded={min(start + batch_size, len(texts))}/{len(texts)}", flush=True)
    embeddings = np.vstack(batches)
    elapsed = time.perf_counter() - started
    if embeddings.shape != (DOCUMENT_COUNT, 768):
        raise ValueError(f"unexpected embedding shape: {embeddings.shape}")
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.isfinite(embeddings).all() or np.any(norms <= 0):
        raise ValueError("cache contains non-finite or zero embeddings")

    with OUTPUT.open("wb") as handle:
        np.savez_compressed(
            handle,
            document_ids=np.asarray(ids, dtype=str),
            embeddings=embeddings,
        )
    metadata = {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_path": str(corpus_path),
        "corpus_sha256": CORPUS_SHA256,
        "document_count": DOCUMENT_COUNT,
        "dimensions": 768,
        "encoder": {
            "model": "allenai/specter2_base",
            "model_revision": SPECTER2_BASE_REVISION,
            "proximity_adapter": "allenai/specter2",
            "proximity_revision": SPECTER2_PROXIMITY_REVISION,
            "query_adapter": "allenai/specter2_adhoc_query",
            "query_revision": SPECTER2_QUERY_REVISION,
            "max_length": 512,
        },
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "adapters": adapters.__version__,
            "device": "cuda",
            "gpu": torch.cuda.get_device_name(0),
            "batch_size": batch_size,
            "elapsed_seconds": elapsed,
        },
        "validation": {
            "shape": list(embeddings.shape),
            "minimum_norm": float(norms.min()),
            "maximum_norm": float(norms.max()),
        },
    }
    metadata_path = OUTPUT.with_suffix(".json")
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = {
        "status": "completed",
        "cache_sha256": file_sha256(OUTPUT),
        "metadata_sha256": file_sha256(metadata_path),
        "metadata": metadata,
    }
    Path("/kaggle/working/run_report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
