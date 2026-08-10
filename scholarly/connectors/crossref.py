from __future__ import annotations

import re
from datetime import date
from typing import Any

from scholarly.normalize import normalize_doi
from scholarly.schema import CanonicalWorkRecord

from .base import BaseConnector


_TAG_RE = re.compile(r"<[^>]+>")


def _first_date(item: dict[str, Any]) -> date | None:
    for field in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(field) or {}).get("date-parts") or []
        if not parts:
            continue
        values = list(parts[0]) + [1, 1]
        try:
            return date(int(values[0]), int(values[1]), int(values[2]))
        except (TypeError, ValueError):
            continue
    return None


class CrossrefConnector(BaseConnector):
    source = "crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, *, email: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.email = email

    def search(self, query: str, *, limit: int = 25) -> list[CanonicalWorkRecord]:
        headers = {
            "User-Agent": (
                f"PaperMetrix/2.0 (mailto:{self.email})"
                if self.email
                else "PaperMetrix/2.0"
            )
        }
        payload = self.get_json(
            self.endpoint,
            params={
                "query.bibliographic": query,
                "rows": min(limit, 1000),
                **({"mailto": self.email} if self.email else {}),
            },
            headers=headers,
        )
        return [
            self._record(item)
            for item in payload.get("message", {}).get("items", [])
            if item.get("DOI") and item.get("title")
        ]

    def _record(self, item: dict[str, Any]) -> CanonicalWorkRecord:
        doi = normalize_doi(item["DOI"])
        published = _first_date(item)
        authors = tuple(
            " ".join(
                part
                for part in (author.get("given", ""), author.get("family", ""))
                if part
            ).strip()
            for author in item.get("author", [])
            if author.get("given") or author.get("family")
        )
        references = tuple(
            ("doi", normalize_doi(reference["DOI"]))
            for reference in item.get("reference", [])
            if reference.get("DOI")
        )
        licenses = item.get("license") or []
        links = item.get("link") or []
        pdf_url = next(
            (
                link.get("URL")
                for link in links
                if link.get("content-type") == "application/pdf"
            ),
            None,
        )
        return CanonicalWorkRecord(
            source=self.source,
            external_id=doi,
            title=item["title"][0],
            abstract=_TAG_RE.sub(" ", item.get("abstract") or "").strip(),
            publication_date=published,
            year=published.year if published else None,
            work_type=item.get("type") or "article",
            venue=(item.get("container-title") or [""])[0],
            publisher=item.get("publisher") or "",
            language=item.get("language") or "",
            authors=authors,
            identifiers={"doi": doi},
            topics=tuple(item.get("subject") or ()),
            citation_count=int(item.get("is-referenced-by-count") or 0),
            reference_count=int(item.get("references-count") or len(references)),
            is_open_access=bool(licenses or pdf_url),
            pdf_url=pdf_url,
            landing_url=item.get("URL") or f"https://doi.org/{doi}",
            references=references,
            raw_payload=item,
        )
