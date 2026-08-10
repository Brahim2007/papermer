from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalWorkRecord:
    source: str
    external_id: str
    title: str
    abstract: str = ""
    publication_date: date | None = None
    year: int | None = None
    work_type: str = "article"
    venue: str = ""
    publisher: str = ""
    language: str = ""
    authors: tuple[str, ...] = ()
    identifiers: dict[str, str] = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    citation_count: int = 0
    reference_count: int = 0
    is_retracted: bool = False
    is_open_access: bool = False
    pdf_url: str | None = None
    landing_url: str = ""
    references: tuple[tuple[str, str], ...] = ()
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source or not self.external_id:
            raise ValueError("source and external_id are required")
        if not self.title.strip():
            raise ValueError("title is required")
