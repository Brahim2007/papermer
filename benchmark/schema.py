from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal


TaskType = Literal["ad_hoc", "related_paper"]


@dataclass(frozen=True, slots=True)
class BenchmarkQuery:
    query_id: str
    text: str
    query_date: date
    task_type: TaskType
    seed_ids: tuple[str, ...] = ()
    stratum: str = ""
    author_id: str = ""

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "BenchmarkQuery":
        query = cls(
            query_id=str(item["query_id"]).strip(),
            text=str(item["query"]).strip(),
            query_date=date.fromisoformat(str(item["query_date"])),
            task_type=str(item.get("task_type", "ad_hoc")),  # type: ignore[arg-type]
            seed_ids=tuple(map(str, item.get("seed_ids", ()))),
            stratum=str(item.get("stratum", "")).strip(),
            author_id=str(item.get("author_id", "")).strip(),
        )
        query.validate()
        return query

    def validate(self) -> None:
        if not self.query_id:
            raise ValueError("query_id must not be empty")
        if not self.text:
            raise ValueError(f"{self.query_id}: query must not be empty")
        if self.task_type not in {"ad_hoc", "related_paper"}:
            raise ValueError(f"{self.query_id}: unsupported task_type")
        if self.task_type == "related_paper" and not self.seed_ids:
            raise ValueError(f"{self.query_id}: related_paper requires seed_ids")
        if self.task_type == "ad_hoc" and self.seed_ids:
            raise ValueError(f"{self.query_id}: ad_hoc queries cannot contain seed_ids")


@dataclass(frozen=True, slots=True)
class Judgment:
    query_id: str
    document_id: str
    assessor_id: str
    relevance: int
    confidence: int | None = None
    rationale: str = ""

    def validate(self) -> None:
        if not self.query_id or not self.document_id or not self.assessor_id:
            raise ValueError("judgment identifiers must not be empty")
        if self.relevance not in {0, 1, 2}:
            raise ValueError("relevance must be 0, 1, or 2")
        if self.confidence is not None and self.confidence not in {1, 2, 3}:
            raise ValueError("confidence must be 1, 2, 3, or blank")
