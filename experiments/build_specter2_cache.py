"""Encode one frozen corpus snapshot once for temporal SPECTER2 evaluation."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import adapters
import pandas as pd
import torch
import transformers

from experiments.build_temporal_benchmark import file_sha256
from retrieval.specter2 import Specter2Encoder
from retrieval.specter_cache import save_specter2_cache


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=("cpu", "cuda"), default=None)
    args = parser.parse_args()

    corpus = pd.read_csv(args.corpus).fillna("")
    required = {"id", "title"}
    missing = required - set(corpus.columns)
    if missing:
        raise ValueError(f"corpus is missing columns: {sorted(missing)}")
    ids = corpus["id"].astype(str).tolist()
    if len(set(ids)) != len(ids):
        raise ValueError("corpus ids must be unique")

    encoder = Specter2Encoder(device=args.device)
    abstract_column = "abstract" if "abstract" in corpus else "text"
    if abstract_column not in corpus:
        raise ValueError("corpus requires an abstract or text column")
    embeddings = encoder.encode_papers(
        corpus["title"].astype(str).tolist(),
        corpus[abstract_column].astype(str).tolist(),
        batch_size=args.batch_size,
    )
    metadata = {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_path": str(args.corpus),
        "corpus_sha256": file_sha256(args.corpus),
        "document_count": len(ids),
        "dimensions": int(embeddings.shape[1]),
        "encoder": encoder.identity(),
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "adapters": adapters.__version__,
            "device": encoder.device,
        },
    }
    save_specter2_cache(
        args.output,
        document_ids=ids,
        embeddings=embeddings,
        metadata=metadata,
    )
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
