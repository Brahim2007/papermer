"""Create an exact corpus-aligned subset of an existing SPECTER2 cache."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from experiments.build_temporal_benchmark import file_sha256
from retrieval.specter_cache import load_specter2_cache, save_specter2_cache


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = load_specter2_cache(args.source_cache)
    document_ids = (
        pd.read_csv(args.corpus, usecols=["id"])["id"].astype(str).tolist()
    )
    embeddings = source.subset(document_ids)
    metadata = {
        **source.metadata,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_path": str(args.corpus),
        "corpus_sha256": file_sha256(args.corpus),
        "document_count": len(document_ids),
        "dimensions": int(embeddings.shape[1]),
        "derivation": {
            "method": "exact_document_id_subset",
            "source_cache": str(args.source_cache),
            "source_cache_sha256": file_sha256(args.source_cache),
            "reason": (
                "exclude provider drift outside the preregistered "
                "parent-corpus-plus-arXiv membership"
            ),
        },
    }
    save_specter2_cache(
        args.output,
        document_ids=document_ids,
        embeddings=embeddings,
        metadata=metadata,
    )
    print(
        {
            "document_count": len(document_ids),
            "dimensions": int(embeddings.shape[1]),
            "corpus_sha256": metadata["corpus_sha256"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
