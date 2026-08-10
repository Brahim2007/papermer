from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .hybrid import reciprocal_rank_fusion
from .tfidf import SearchResult


@dataclass(frozen=True, slots=True)
class CitationEdge:
    citing_document_id: str
    cited_reference_key: str
    cited_document_id: str | None = None


@dataclass(frozen=True, slots=True)
class CitationGraphArtifact:
    edges: tuple[CitationEdge, ...]
    metadata: dict


def load_citation_graph(path: Path) -> CitationGraphArtifact:
    metadata_path = path.with_suffix(".manifest.json")
    if not path.exists() or not metadata_path.exists():
        raise FileNotFoundError(
            f"citation graph requires {path.name} and {metadata_path.name}"
        )
    edges = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            edges.append(
                CitationEdge(
                    citing_document_id=str(row["citing_document_id"]),
                    cited_reference_key=str(row["cited_reference_key"]),
                    cited_document_id=(
                        str(row["cited_document_id"])
                        if row.get("cited_document_id")
                        else None
                    ),
                )
            )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("edge_count") != len(edges):
        raise ValueError("citation graph edge count does not match its manifest")
    return CitationGraphArtifact(tuple(edges), metadata)


class CitationGraphRetriever:
    """Direct citation, bibliographic coupling, and co-citation retrieval."""

    def __init__(
        self,
        *,
        direct_weight: float = 1.0,
        bibliographic_weight: float = 1.0,
        cocitation_weight: float = 1.0,
    ) -> None:
        for value in (direct_weight, bibliographic_weight, cocitation_weight):
            if value < 0:
                raise ValueError("graph weights must be non-negative")
        self.direct_weight = direct_weight
        self.bibliographic_weight = bibliographic_weight
        self.cocitation_weight = cocitation_weight
        self._document_ids: set[str] = set()
        self._out_references: dict[str, set[str]] = defaultdict(set)
        self._reference_citers: dict[str, set[str]] = defaultdict(set)
        self._out_internal: dict[str, set[str]] = defaultdict(set)
        self._in_citers: dict[str, set[str]] = defaultdict(set)

    def fit(
        self,
        document_ids: Sequence[str],
        edges: Sequence[CitationEdge],
    ) -> "CitationGraphRetriever":
        self._document_ids = set(map(str, document_ids))
        if len(self._document_ids) != len(document_ids):
            raise ValueError("document ids must be unique")
        for edge in edges:
            citing = str(edge.citing_document_id)
            if citing not in self._document_ids:
                continue
            self._out_references[citing].add(edge.cited_reference_key)
            self._reference_citers[edge.cited_reference_key].add(citing)
            cited = str(edge.cited_document_id) if edge.cited_document_id else ""
            if cited and cited in self._document_ids and cited != citing:
                self._out_internal[citing].add(cited)
                self._in_citers[cited].add(citing)
        return self

    def search_from_seeds(
        self,
        seed_ids: Sequence[str] | Mapping[str, float],
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        weights = (
            {str(key): float(value) for key, value in seed_ids.items()}
            if isinstance(seed_ids, Mapping)
            else {str(seed_id): 1.0 for seed_id in seed_ids}
        )
        unknown = set(weights) - self._document_ids
        if unknown:
            raise ValueError(f"unknown graph seed ids: {sorted(unknown)[:3]}")
        scores: dict[str, float] = defaultdict(float)

        for seed, seed_weight in weights.items():
            if seed_weight < 0:
                raise ValueError("seed weights must be non-negative")
            for candidate in self._out_internal[seed] | self._in_citers[seed]:
                scores[candidate] += seed_weight * self.direct_weight

            seed_refs = self._out_references[seed]
            coupling_counts: dict[str, int] = defaultdict(int)
            for reference in seed_refs:
                for candidate in self._reference_citers[reference]:
                    if candidate != seed:
                        coupling_counts[candidate] += 1
            for candidate, overlap in coupling_counts.items():
                denominator = math.sqrt(
                    max(len(seed_refs), 1)
                    * max(len(self._out_references[candidate]), 1)
                )
                scores[candidate] += (
                    seed_weight
                    * self.bibliographic_weight
                    * overlap
                    / denominator
                )

            seed_citers = self._in_citers[seed]
            cocitation_counts: dict[str, int] = defaultdict(int)
            for citer in seed_citers:
                for candidate in self._out_internal[citer]:
                    if candidate != seed:
                        cocitation_counts[candidate] += 1
            for candidate, overlap in cocitation_counts.items():
                denominator = math.sqrt(
                    max(len(seed_citers), 1)
                    * max(len(self._in_citers[candidate]), 1)
                )
                scores[candidate] += (
                    seed_weight
                    * self.cocitation_weight
                    * overlap
                    / denominator
                )

        excluded = set(map(str, exclude_ids)) | set(weights)
        ordered = sorted(
            (
                (document_id, score)
                for document_id, score in scores.items()
                if document_id not in excluded and score > 0
            ),
            key=lambda item: (-item[1], item[0]),
        )[:top_k]
        return [
            SearchResult(document_id, float(score), rank)
            for rank, (document_id, score) in enumerate(ordered, start=1)
        ]


class GraphExpansionRetriever:
    """Use text retrieval as graph seeds, then fuse text and graph rankings."""

    def __init__(
        self,
        base_retriever,
        graph_retriever: CitationGraphRetriever,
        *,
        seed_k: int = 10,
        rrf_k: int = 60,
        fuse_base: bool = True,
    ) -> None:
        self.base_retriever = base_retriever
        self.graph_retriever = graph_retriever
        self.seed_k = seed_k
        self.rrf_k = rrf_k
        self.fuse_base = fuse_base

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        base = list(
            self.base_retriever.search(
                query, top_k=max(top_k, self.seed_k), exclude_ids=exclude_ids
            )
        )
        seed_weights = {
            result.document_id: 1.0 / result.rank
            for result in base[: self.seed_k]
        }
        graph = self.graph_retriever.search_from_seeds(
            seed_weights,
            top_k=max(top_k, self.seed_k * 5),
            exclude_ids=exclude_ids,
        )
        if not self.fuse_base:
            return graph[:top_k]
        fused = reciprocal_rank_fusion(
            {"base": base, "graph": graph}, rrf_k=self.rrf_k, top_k=top_k
        )
        return [
            SearchResult(item.document_id, item.score, item.rank) for item in fused
        ]

    def search_with_seeds(
        self,
        query: str,
        seed_ids: Sequence[str],
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        if seed_ids:
            return self.graph_retriever.search_from_seeds(
                seed_ids,
                top_k=top_k,
                exclude_ids=exclude_ids,
            )
        return self.search(query, top_k=top_k, exclude_ids=exclude_ids)


class CitationHybridRetriever:
    """Fuse lexical, dense, and citation-graph rankings with optional seeds."""

    def __init__(
        self,
        text_retrievers: Mapping[str, object],
        graph_retriever: CitationGraphRetriever,
        *,
        rrf_k: int = 60,
        candidate_k: int = 100,
        graph_seed_k: int = 10,
        weights: Mapping[str, float] | None = None,
    ) -> None:
        self.text_retrievers = dict(text_retrievers)
        self.graph_retriever = graph_retriever
        self.rrf_k = rrf_k
        self.candidate_k = candidate_k
        self.graph_seed_k = graph_seed_k
        self.weights = dict(weights or {})

    def search_with_seeds(
        self,
        query: str,
        seed_ids: Sequence[str],
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        rankings = {
            name: retriever.search(
                query,
                top_k=self.candidate_k,
                exclude_ids=exclude_ids,
            )
            for name, retriever in self.text_retrievers.items()
        }
        if seed_ids:
            graph_seeds: Sequence[str] | Mapping[str, float] = seed_ids
        else:
            first_ranking = next(iter(rankings.values()), [])
            graph_seeds = {
                result.document_id: 1.0 / result.rank
                for result in first_ranking[: self.graph_seed_k]
            }
        rankings["citation_graph"] = self.graph_retriever.search_from_seeds(
            graph_seeds,
            top_k=self.candidate_k,
            exclude_ids=exclude_ids,
        )
        fused = reciprocal_rank_fusion(
            rankings,
            rrf_k=self.rrf_k,
            weights=self.weights,
            top_k=top_k,
        )
        return [
            SearchResult(item.document_id, item.score, item.rank) for item in fused
        ]

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        exclude_ids: Iterable[str] = (),
    ) -> list[SearchResult]:
        return self.search_with_seeds(
            query, (), top_k=top_k, exclude_ids=exclude_ids
        )
