from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class Specter2CorpusCache:
    document_ids: tuple[str, ...]
    embeddings: np.ndarray
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if self.embeddings.ndim != 2:
            raise ValueError("cached embeddings must be a two-dimensional matrix")
        if len(self.document_ids) != self.embeddings.shape[0]:
            raise ValueError("cached document ids and embedding rows must align")
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("cached document ids must be unique")

    def subset(self, document_ids: Sequence[str]) -> np.ndarray:
        positions = {
            document_id: index for index, document_id in enumerate(self.document_ids)
        }
        missing = [str(item) for item in document_ids if str(item) not in positions]
        if missing:
            preview = ", ".join(missing[:3])
            raise ValueError(f"SPECTER2 cache is missing document ids: {preview}")
        return np.vstack(
            [self.embeddings[positions[str(document_id)]] for document_id in document_ids]
        ).astype(np.float32, copy=False)


def save_specter2_cache(
    path: Path,
    *,
    document_ids: Sequence[str],
    embeddings: np.ndarray,
    metadata: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_ids = np.asarray(list(map(str, document_ids)), dtype=str)
    normalized_embeddings = np.asarray(embeddings, dtype=np.float32)
    cache = Specter2CorpusCache(
        tuple(normalized_ids.tolist()), normalized_embeddings, metadata
    )
    with path.open("wb") as handle:
        np.savez_compressed(
            handle,
            document_ids=normalized_ids,
            embeddings=cache.embeddings,
        )
    path.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_specter2_cache(path: Path) -> Specter2CorpusCache:
    metadata_path = path.with_suffix(".json")
    if not path.exists() or not metadata_path.exists():
        raise FileNotFoundError(
            f"SPECTER2 cache requires {path.name} and {metadata_path.name}"
        )
    with np.load(path, allow_pickle=False) as payload:
        document_ids = tuple(payload["document_ids"].astype(str).tolist())
        embeddings = payload["embeddings"].astype(np.float32)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return Specter2CorpusCache(document_ids, embeddings, metadata)
