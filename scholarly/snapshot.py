from __future__ import annotations

import gzip
import hashlib
import heapq
import json
from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from scholarly.normalize import normalize_openalex_id


def file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def open_snapshot(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_jsonl(path: Path, *, skip_lines: int = 0) -> Iterator[tuple[int, dict]]:
    with open_snapshot(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number <= skip_lines or not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number}: JSON value must be an object")
            yield line_number, payload


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _topic_hierarchy_values(item: dict) -> tuple[set[str], set[str]]:
    """Return normalized names and IDs from every OpenAlex topic hierarchy level."""
    names: set[str] = set()
    identifiers: set[str] = set()
    topics = list(item.get("topics") or item.get("concepts") or ())
    primary = item.get("primary_topic")
    if primary:
        topics.append(primary)
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        for node in (
            topic,
            topic.get("subfield"),
            topic.get("field"),
            topic.get("domain"),
        ):
            if not isinstance(node, dict):
                continue
            name = str(node.get("display_name") or "").strip().casefold()
            if name:
                names.add(name)
            identifier = str(node.get("id") or "").strip().rstrip("/").casefold()
            if identifier:
                identifiers.add(identifier)
                identifiers.add(identifier.rsplit("/", 1)[-1])
    return names, identifiers


def openalex_scope_rejection(item: dict, spec: dict) -> str | None:
    """Return a stable rejection code, or None when an OpenAlex work is eligible."""
    if not item.get("id"):
        return "missing_id"
    if not str(item.get("display_name") or item.get("title") or "").strip():
        return "missing_title"
    publication_date = _parse_date(item.get("publication_date"))
    if publication_date is None:
        return "missing_or_invalid_date"
    if not (
        date.fromisoformat(spec["from_date"])
        <= publication_date
        <= date.fromisoformat(spec["to_date"])
    ):
        return "outside_date_range"
    languages = {str(value).casefold() for value in spec.get("languages", ())}
    if languages and str(item.get("language") or "").casefold() not in languages:
        return "language"
    work_types = {
        str(value).casefold() for value in spec.get("openalex_work_types", ())
    }
    if work_types and str(item.get("type") or "").casefold() not in work_types:
        return "work_type"
    if spec.get("require_abstract") and not item.get("abstract_inverted_index"):
        return "missing_abstract"
    if spec.get("exclude_retracted", True) and item.get("is_retracted"):
        return "retracted"
    included_topics = {
        str(value).strip().casefold() for value in spec.get("include_topics", ())
    }
    included_topic_ids = {
        str(value).strip().rstrip("/").casefold()
        for value in spec.get("include_topic_ids", ())
    }
    names, identifiers = _topic_hierarchy_values(item)
    if (included_topics or included_topic_ids) and not (
        (names & included_topics) or (identifiers & included_topic_ids)
    ):
        return "topic"
    return None


def validate_bulk_scope(spec: dict) -> None:
    if spec.get("protocol") == "openalex_shared_reference_closure_v1":
        required = {
            "format_version",
            "name",
            "protocol",
            "parent_corpus_sha256",
            "from_date",
            "to_date",
            "target_addition_count",
            "candidate_pool_cap",
            "min_distinct_parent_citers",
            "selection",
        }
        missing = sorted(required - set(spec))
        if missing:
            raise ValueError(f"citation closure scope is missing: {missing}")
        if date.fromisoformat(spec["to_date"]) < date.fromisoformat(spec["from_date"]):
            raise ValueError("scope to_date precedes from_date")
        target = int(spec["target_addition_count"])
        if target < 1 or int(spec["candidate_pool_cap"]) < target:
            raise ValueError("citation closure target and candidate cap are invalid")
        if int(spec["min_distinct_parent_citers"]) < 2:
            raise ValueError("citation closure requires at least two parent citers")
        if not (spec.get("include_topics") or spec.get("include_topic_ids")):
            raise ValueError("at least one topical scope selector is required")
        if spec["selection"].get("reference_scheme") != "openalex":
            raise ValueError("citation closure currently requires OpenAlex references")
        return
    required = {
        "format_version",
        "name",
        "source_format",
        "from_date",
        "to_date",
        "target_document_count",
        "sampling",
    }
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError(f"bulk scope is missing: {missing}")
    if spec["source_format"] != "openalex_jsonl":
        raise ValueError("only openalex_jsonl snapshots are currently supported")
    if date.fromisoformat(spec["to_date"]) < date.fromisoformat(spec["from_date"]):
        raise ValueError("scope to_date precedes from_date")
    if int(spec["target_document_count"]) < 1:
        raise ValueError("target_document_count must be positive")
    if not (spec.get("include_topics") or spec.get("include_topic_ids")):
        raise ValueError("at least one topical scope selector is required")
    sampling = spec["sampling"]
    method = sampling.get("method")
    supported = {
        "deterministic_sha256_bottom_k",
        "openalex_seeded_stratified_sample_v1",
    }
    if method not in supported:
        raise ValueError(f"unsupported sampling method: {method}")
    if sampling.get("seed") in (None, ""):
        raise ValueError("sampling seed is required")
    if method == "openalex_seeded_stratified_sample_v1":
        strata = sampling.get("strata")
        if not isinstance(strata, list) or not strata:
            raise ValueError("seeded stratified sampling requires strata")
        names = [str(item.get("name") or "") for item in strata]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("sampling stratum names must be non-empty and unique")
        quota_total = sum(int(item.get("quota") or 0) for item in strata)
        if quota_total != int(spec["target_document_count"]):
            raise ValueError("sampling stratum quotas must equal target_document_count")
        for item in strata:
            if int(item.get("quota") or 0) < 1:
                raise ValueError("sampling stratum quota must be positive")
            if item.get("seed") in (None, ""):
                raise ValueError("every sampling stratum requires a seed")
            reserve_seeds = item.get("reserve_seeds")
            if not isinstance(reserve_seeds, list) or not reserve_seeds:
                raise ValueError("every sampling stratum requires reserve seeds")
            if len({item["seed"], *reserve_seeds}) != 1 + len(reserve_seeds):
                raise ValueError("sampling seeds must be unique within each stratum")
            if not str(item.get("primary_topic_subfield_id") or "").strip():
                raise ValueError("every sampling stratum requires a subfield ID")
            if not item.get("work_types"):
                raise ValueError("every sampling stratum requires work types")


def snapshot_target_count(spec: dict) -> int:
    if spec.get("protocol") == "openalex_shared_reference_closure_v1":
        return int(spec["target_addition_count"])
    return int(spec["target_document_count"])


def deterministic_sample(
    rows: Iterator[dict], *, spec: dict
) -> tuple[list[dict], Counter[str]]:
    """Select popularity-neutral bottom-k records by stable OpenAlex ID hash."""
    validate_bulk_scope(spec)
    if spec["sampling"]["method"] != "deterministic_sha256_bottom_k":
        raise ValueError("deterministic_sample requires bottom-k sampling")
    target = int(spec["target_document_count"])
    seed = str(spec["sampling"]["seed"])
    heap: list[tuple[int, str, dict]] = []
    rejections: Counter[str] = Counter()
    seen_ids: set[str] = set()
    for item in rows:
        rejection = openalex_scope_rejection(item, spec)
        if rejection:
            rejections[rejection] += 1
            continue
        openalex_id = normalize_openalex_id(str(item["id"]))
        if openalex_id in seen_ids:
            rejections["duplicate_openalex_id"] += 1
            continue
        seen_ids.add(openalex_id)
        score = int.from_bytes(
            hashlib.sha256(f"{seed}\0{openalex_id}".encode()).digest(), "big"
        )
        entry = (-score, openalex_id, item)
        if len(heap) < target:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
    selected = [(-negative, identifier, item) for negative, identifier, item in heap]
    selected.sort(key=lambda value: (value[0], value[1]))
    return [item for _, _, item in selected], rejections
