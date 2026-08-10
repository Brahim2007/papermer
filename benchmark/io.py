from __future__ import annotations

import csv
import json
from pathlib import Path

from .schema import BenchmarkQuery, Judgment


def read_benchmark_queries(path: Path) -> list[BenchmarkQuery]:
    queries = []
    seen = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                query = BenchmarkQuery.from_dict(json.loads(line))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid query at line {line_number}: {exc}") from exc
            if query.query_id in seen:
                raise ValueError(f"duplicate query_id: {query.query_id}")
            seen.add(query.query_id)
            queries.append(query)
    if not queries:
        raise ValueError("query file must contain at least one query")
    return queries


def read_judgments(path: Path, *, assessor_id: str | None = None) -> list[Judgment]:
    judgments = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            raw_relevance = str(row.get("relevance", "")).strip()
            if not raw_relevance:
                raise ValueError(f"{path}:{line_number}: relevance is blank")
            raw_confidence = str(row.get("confidence", "")).strip()
            judgment = Judgment(
                query_id=str(row.get("query_id", "")).strip(),
                document_id=str(row.get("document_id", "")).strip(),
                assessor_id=(
                    assessor_id or str(row.get("assessor_id", "")).strip()
                ),
                relevance=int(raw_relevance),
                confidence=int(raw_confidence) if raw_confidence else None,
                rationale=str(row.get("rationale", "")).strip(),
            )
            judgment.validate()
            key = (judgment.query_id, judgment.document_id, judgment.assessor_id)
            if key in seen:
                raise ValueError(f"{path}:{line_number}: duplicate judgment {key}")
            seen.add(key)
            judgments.append(judgment)
    if not judgments:
        raise ValueError(f"{path}: no judgments found")
    return judgments
