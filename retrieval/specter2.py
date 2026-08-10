from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from .tfidf import SearchResult

SPECTER2_BASE_REVISION = "3447645e1def9117997203454fa4495937bfbd83"
SPECTER2_PROXIMITY_REVISION = "2081559630a80fc5851d8f798a05ba81e9468089"
SPECTER2_QUERY_REVISION = "3f4448817028388648a74349ece07af4518ec5bd"


class ScientificEncoder(Protocol):
    def encode_papers(
        self, titles: Sequence[str], abstracts: Sequence[str], *, batch_size: int = 16
    ) -> np.ndarray: ...

    def encode_queries(
        self, queries: Sequence[str], *, batch_size: int = 16
    ) -> np.ndarray: ...


class Specter2Encoder:
    """Official SPECTER2 base model with proximity and ad-hoc query adapters."""

    def __init__(
        self,
        *,
        model_name: str = "allenai/specter2_base",
        proximity_adapter: str = "allenai/specter2",
        query_adapter: str = "allenai/specter2_adhoc_query",
        model_revision: str = SPECTER2_BASE_REVISION,
        proximity_revision: str = SPECTER2_PROXIMITY_REVISION,
        query_revision: str = SPECTER2_QUERY_REVISION,
        device: str | None = None,
        max_length: int = 512,
    ) -> None:
        self.model_name = model_name
        self.proximity_adapter = proximity_adapter
        self.query_adapter = query_adapter
        self.model_revision = model_revision
        self.proximity_revision = proximity_revision
        self.query_revision = query_revision
        self.device = device
        self.max_length = max_length
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        import torch
        from adapters import AutoAdapterModel
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, revision=self.model_revision
        )
        self._model = AutoAdapterModel.from_pretrained(
            self.model_name, revision=self.model_revision
        )
        self._model.load_adapter(
            self.proximity_adapter,
            source="hf",
            load_as="proximity",
            revision=self.proximity_revision,
        )
        self._model.load_adapter(
            self.query_adapter,
            source="hf",
            load_as="adhoc_query",
            revision=self.query_revision,
        )
        self._model.set_active_adapters("proximity")
        target_device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(target_device)
        self._model.eval()
        self.device = target_device

    def identity(self) -> dict[str, str | int]:
        return {
            "model": self.model_name,
            "model_revision": self.model_revision,
            "proximity_adapter": self.proximity_adapter,
            "proximity_revision": self.proximity_revision,
            "query_adapter": self.query_adapter,
            "query_revision": self.query_revision,
            "max_length": self.max_length,
        }

    def _encode(
        self, texts: Sequence[str], *, adapter: str, batch_size: int
    ) -> np.ndarray:
        self._load()
        import torch
        import torch.nn.functional as functional

        assert self._model is not None and self._tokenizer is not None
        self._model.set_active_adapters(adapter)
        batches = []
        for start in range(0, len(texts), batch_size):
            encoded = self._tokenizer(
                list(texts[start : start + batch_size]),
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
                max_length=self.max_length,
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with torch.inference_mode():
                output = self._model(**encoded)
                embedding = functional.normalize(
                    output.last_hidden_state[:, 0, :], p=2, dim=1
                )
            batches.append(embedding.cpu().numpy().astype(np.float32))
        if not batches:
            return np.empty((0, 768), dtype=np.float32)
        return np.vstack(batches)

    def encode_papers(
        self, titles: Sequence[str], abstracts: Sequence[str], *, batch_size: int = 16
    ) -> np.ndarray:
        if len(titles) != len(abstracts):
            raise ValueError("titles and abstracts must have the same length")
        self._load()
        separator = self._tokenizer.sep_token or " [SEP] "  # type: ignore[union-attr]
        texts = [
            f"{title}{separator}{abstract or ''}"
            for title, abstract in zip(titles, abstracts, strict=True)
        ]
        return self._encode(texts, adapter="proximity", batch_size=batch_size)

    def encode_queries(
        self, queries: Sequence[str], *, batch_size: int = 16
    ) -> np.ndarray:
        return self._encode(queries, adapter="adhoc_query", batch_size=batch_size)


class Specter2Retriever:
    def __init__(self, encoder: ScientificEncoder | None = None) -> None:
        self.encoder = encoder or Specter2Encoder()
        self._document_ids: list[str] = []
        self._embeddings: np.ndarray | None = None
        self.cache_hit = False
        self.cache_key = ""

    @property
    def corpus_size(self) -> int:
        return len(self._document_ids)

    def fit(
        self,
        document_ids: Sequence[str],
        titles: Sequence[str],
        abstracts: Sequence[str],
        *,
        batch_size: int = 16,
        cache_dir: Path | str | None = None,
    ) -> "Specter2Retriever":
        if not (len(document_ids) == len(titles) == len(abstracts)):
            raise ValueError("document ids, titles, and abstracts must align")
        if not document_ids:
            raise ValueError("cannot fit a retriever on an empty corpus")
        cache_path = None
        metadata_path = None
        if cache_dir is not None:
            identity = getattr(self.encoder, "identity", lambda: {})()
            digest = hashlib.sha256()
            digest.update(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            )
            for document_id, title, abstract in zip(
                document_ids, titles, abstracts, strict=True
            ):
                digest.update(
                    json.dumps(
                        [str(document_id), title, abstract],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
            self.cache_key = digest.hexdigest()
            cache_root = Path(cache_dir)
            cache_path = cache_root / f"{self.cache_key}.npz"
            metadata_path = cache_root / f"{self.cache_key}.json"

        embeddings = None
        if cache_path and cache_path.exists():
            with np.load(cache_path, allow_pickle=False) as cached:
                cached_ids = cached["document_ids"].astype(str).tolist()
                cached_embeddings = cached["embeddings"].astype(np.float32)
            if cached_ids == list(map(str, document_ids)):
                embeddings = cached_embeddings
                self.cache_hit = True
        if embeddings is None:
            embeddings = self.encoder.encode_papers(
                titles, abstracts, batch_size=batch_size
            )
            if cache_path and metadata_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(
                    cache_path,
                    document_ids=np.asarray(document_ids, dtype=str),
                    embeddings=np.asarray(embeddings, dtype=np.float32),
                )
                metadata_path.write_text(
                    json.dumps(
                        {
                            "cache_key": self.cache_key,
                            "document_count": len(document_ids),
                            "dimensions": (
                                int(embeddings.shape[1]) if embeddings.ndim == 2 else 0
                            ),
                            "encoder": getattr(self.encoder, "identity", lambda: {})(),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        if embeddings.shape[0] != len(document_ids):
            raise ValueError("encoder returned an unexpected number of embeddings")
        return self.fit_embeddings(document_ids, embeddings)

    def fit_embeddings(
        self,
        document_ids: Sequence[str],
        embeddings: np.ndarray,
    ) -> "Specter2Retriever":
        if not document_ids:
            raise ValueError("cannot fit a retriever on an empty corpus")
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(document_ids):
            raise ValueError("document ids and embedding rows must align")
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        self._embeddings = embeddings / np.maximum(norms, 1e-12)
        self._document_ids = [str(document_id) for document_id in document_ids]
        return self

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if self._embeddings is None:
            raise RuntimeError("fit must be called before search")
        if not query.strip():
            raise ValueError("query must not be empty")
        query_embedding = self.encoder.encode_queries([query])[0]
        query_embedding = query_embedding / max(
            float(np.linalg.norm(query_embedding)), 1e-12
        )
        scores = self._embeddings @ query_embedding
        excluded = {str(document_id) for document_id in exclude_ids}
        target = min(
            top_k,
            sum(document_id not in excluded for document_id in self._document_ids),
        )
        results = []
        for index in np.argsort(-scores, kind="mergesort"):
            document_id = self._document_ids[int(index)]
            if document_id in excluded:
                continue
            results.append(
                SearchResult(
                    document_id=document_id,
                    score=float(scores[int(index)]),
                    rank=len(results) + 1,
                )
            )
            if len(results) == target:
                break
        return results
