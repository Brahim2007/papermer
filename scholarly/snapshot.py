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


def _topic_names(item: dict) -> set[str]:
    topics = list(item.get("topics") or item.get("concepts") or ())
    primary = item.get("primary_topic")
    if primary:
        topics.append(primary)
    return {
        str(topic.get("display_name") or "").strip().casefold()
        for topic in topics
        if isinstance(topic, dict) and topic.get("display_name")
    }


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
    if included_topics and not (_topic_names(item) & included_topics):
        return "topic"
    return None


def validate_bulk_scope(spec: dict) -> None:
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
    sampling = spec["sampling"]
    if sampling.get("method") != "deterministic_sha256_bottom_k":
        raise ValueError("scope must use deterministic_sha256_bottom_k sampling")
    if not str(sampling.get("seed") or "").strip():
        raise ValueError("sampling seed is required")


def deterministic_sample(
    rows: Iterator[dict], *, spec: dict
) -> tuple[list[dict], Counter[str]]:
    """Select popularity-neutral bottom-k records by stable OpenAlex ID hash."""
    validate_bulk_scope(spec)
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
