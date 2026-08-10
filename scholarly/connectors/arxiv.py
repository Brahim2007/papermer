from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from scholarly.normalize import normalize_arxiv_id, normalize_doi
from scholarly.schema import CanonicalWorkRecord

from .base import BaseConnector


_ATOM = "http://www.w3.org/2005/Atom"
_ARXIV = "http://arxiv.org/schemas/atom"
_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)


def _text(element: ET.Element, path: str, default: str = "") -> str:
    child = element.find(path)
    return " ".join((child.text or "").split()) if child is not None else default


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


class ArxivConnector(BaseConnector):
    source = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, *, min_interval_seconds: float = 3.0, **kwargs) -> None:
        super().__init__(min_interval_seconds=min_interval_seconds, **kwargs)

    def search(self, query: str, *, limit: int = 25) -> list[CanonicalWorkRecord]:
        expression = self._text_expression(query)
        return self._query(
            {
                "search_query": expression,
                "start": 0,
                "max_results": min(limit, 100),
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )

    def search_scoped(
        self,
        query: str,
        *,
        from_date: date,
        to_date: date,
        limit: int,
        categories: tuple[str, ...] = (),
        sort: str = "relevance",
    ) -> list[CanonicalWorkRecord]:
        parts = [
            self._text_expression(query),
            (
                f"submittedDate:[{from_date.strftime('%Y%m%d')}0000 "
                f"TO {to_date.strftime('%Y%m%d')}2359]"
            ),
        ]
        safe_categories = tuple(
            category
            for category in categories
            if re.fullmatch(r"[A-Za-z0-9.-]+", category)
        )
        if safe_categories:
            parts.append(
                "("
                + " OR ".join(f"cat:{category}" for category in safe_categories)
                + ")"
            )
        return self._query(
            {
                "search_query": " AND ".join(parts),
                "start": 0,
                "max_results": min(limit, 100),
                "sortBy": sort,
                "sortOrder": "descending",
            }
        )

    def lookup(self, arxiv_id: str) -> CanonicalWorkRecord | None:
        records = self._query(
            {"id_list": arxiv_id.strip(), "start": 0, "max_results": 1}
        )
        return records[0] if records else None

    def lookup_by_doi(self, doi: str) -> CanonicalWorkRecord | None:
        records = self._query(
            {
                "search_query": f'doi:"{normalize_doi(doi)}"',
                "start": 0,
                "max_results": 5,
            }
        )
        normalized = normalize_doi(doi)
        return next(
            (
                record
                for record in records
                if record.identifiers.get("doi") == normalized
            ),
            None,
        )

    def _query(self, params: dict) -> list[CanonicalWorkRecord]:
        xml = self.get_text(
            self.endpoint,
            params=params,
            headers={"User-Agent": "PaperMetrix/2.0 scholarly-metadata-client"},
        )
        root = ET.fromstring(xml)
        return [
            self._record(entry)
            for entry in root.findall(f"{{{_ATOM}}}entry")
            if _text(entry, f"{{{_ATOM}}}title")
        ]

    @staticmethod
    def _text_expression(query: str) -> str:
        escaped = query.strip().replace('"', r"\"")
        return f'all:"{escaped}"'

    def _record(self, entry: ET.Element) -> CanonicalWorkRecord:
        entry_url = _text(entry, f"{{{_ATOM}}}id")
        versioned_id = (
            entry_url.split("/abs/", 1)[-1].rstrip("/").lower()
            if "/abs/" in entry_url
            else entry_url.rstrip("/").rsplit("/", 1)[-1].lower()
        )
        arxiv_id = normalize_arxiv_id(versioned_id)
        doi = normalize_doi(_text(entry, f"{{{_ARXIV}}}doi"))
        identifiers = {"arxiv": arxiv_id}
        if doi:
            identifiers["doi"] = doi
        links = [
            {
                "href": link.attrib.get("href", ""),
                "rel": link.attrib.get("rel", ""),
                "type": link.attrib.get("type", ""),
                "title": link.attrib.get("title", ""),
            }
            for link in entry.findall(f"{{{_ATOM}}}link")
        ]
        pdf_url = next(
            (
                link["href"]
                for link in links
                if link["type"] == "application/pdf" or link["title"] == "pdf"
            ),
            f"https://arxiv.org/pdf/{arxiv_id}",
        )
        landing_url = next(
            (
                link["href"]
                for link in links
                if link["rel"] == "alternate" and link["type"] == "text/html"
            ),
            f"https://arxiv.org/abs/{versioned_id}",
        )
        authors = tuple(
            _text(author, f"{{{_ATOM}}}name")
            for author in entry.findall(f"{{{_ATOM}}}author")
            if _text(author, f"{{{_ATOM}}}name")
        )
        categories = tuple(
            category.attrib.get("term", "")
            for category in entry.findall(f"{{{_ATOM}}}category")
            if category.attrib.get("term")
        )
        published = _date(_text(entry, f"{{{_ATOM}}}published"))
        raw_payload = {
            "id": entry_url,
            "updated": _text(entry, f"{{{_ATOM}}}updated"),
            "published": _text(entry, f"{{{_ATOM}}}published"),
            "title": _text(entry, f"{{{_ATOM}}}title"),
            "summary": _text(entry, f"{{{_ATOM}}}summary"),
            "authors": list(authors),
            "categories": list(categories),
            "doi": doi,
            "journal_ref": _text(entry, f"{{{_ARXIV}}}journal_ref"),
            "links": links,
        }
        return CanonicalWorkRecord(
            source=self.source,
            external_id=versioned_id,
            title=raw_payload["title"],
            abstract=raw_payload["summary"],
            publication_date=published,
            year=published.year if published else None,
            work_type="preprint",
            venue="arXiv",
            publisher="Cornell University",
            authors=authors,
            identifiers=identifiers,
            topics=categories,
            is_open_access=True,
            pdf_url=pdf_url,
            landing_url=landing_url,
            raw_payload=raw_payload,
        )
