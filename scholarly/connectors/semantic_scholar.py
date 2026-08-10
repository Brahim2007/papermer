from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from scholarly.normalize import normalize_arxiv_id, normalize_doi
from scholarly.schema import CanonicalWorkRecord

from .base import BaseConnector, ConnectorRequestError


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class SemanticScholarConnector(BaseConnector):
    source = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    paper_endpoint = "https://api.semanticscholar.org/graph/v1/paper"
    fields = ",".join(
        (
            "title",
            "abstract",
            "year",
            "authors",
            "externalIds",
            "publicationDate",
            "citationCount",
            "referenceCount",
            "openAccessPdf",
            "fieldsOfStudy",
            "publicationTypes",
            "url",
            "venue",
            "references.paperId",
        )
    )

    def __init__(
        self,
        *,
        api_key: str = "",
        min_interval_seconds: float = 1.1,
        **kwargs,
    ) -> None:
        super().__init__(
            min_interval_seconds=min_interval_seconds,
            **kwargs,
        )
        self.api_key = api_key

    def search(self, query: str, *, limit: int = 25) -> list[CanonicalWorkRecord]:
        payload = self.get_json(
            self.endpoint,
            params={"query": query.replace("-", " "), "limit": min(limit, 100), "fields": self.fields},
            headers={"x-api-key": self.api_key} if self.api_key else None,
        )
        return [self._record(item) for item in payload.get("data", [])]

    def search_scoped(
        self,
        query: str,
        *,
        from_date: date,
        to_date: date,
        limit: int,
        publication_types: tuple[str, ...] = (),
        fields_of_study: tuple[str, ...] = (),
    ) -> list[CanonicalWorkRecord]:
        params = {
            "query": query.replace("-", " "),
            "limit": min(limit, 100),
            "fields": self.fields,
            "year": f"{from_date.year}-{to_date.year}",
        }
        if publication_types:
            params["publicationTypes"] = ",".join(publication_types)
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)
        payload = self.get_json(
            self.endpoint,
            params=params,
            headers={"x-api-key": self.api_key} if self.api_key else None,
        )
        records = [self._record(item) for item in payload.get("data", [])]
        return [
            record
            for record in records
            if record.publication_date is None
            or from_date <= record.publication_date <= to_date
        ]

    def lookup(
        self,
        *,
        semantic_scholar_id: str = "",
        doi: str = "",
        arxiv_id: str = "",
    ) -> CanonicalWorkRecord | None:
        if semantic_scholar_id:
            identifier = semantic_scholar_id
        elif doi:
            identifier = f"DOI:{normalize_doi(doi)}"
        elif arxiv_id:
            identifier = f"ARXIV:{normalize_arxiv_id(arxiv_id)}"
        else:
            return None
        try:
            payload = self.get_json(
                f"{self.paper_endpoint}/{quote(identifier, safe='')}",
                params={"fields": self.fields},
                headers={"x-api-key": self.api_key} if self.api_key else None,
            )
        except ConnectorRequestError as exc:
            if exc.status_code == 404:
                return None
            raise
        return self._record(payload)

    def _record(self, item: dict[str, Any]) -> CanonicalWorkRecord:
        external = item.get("externalIds") or {}
        identifiers = {"s2": item["paperId"]}
        if external.get("DOI"):
            identifiers["doi"] = normalize_doi(external["DOI"])
        if external.get("ArXiv"):
            identifiers["arxiv"] = normalize_arxiv_id(external["ArXiv"])
        if external.get("PubMed"):
            identifiers["pmid"] = str(external["PubMed"])
        oa = item.get("openAccessPdf") or {}
        references = tuple(
            ("s2", reference["paperId"])
            for reference in item.get("references") or []
            if reference.get("paperId")
        )
        publication_types = item.get("publicationTypes") or []
        return CanonicalWorkRecord(
            source=self.source,
            external_id=item["paperId"],
            title=item.get("title") or "Untitled",
            abstract=item.get("abstract") or "",
            publication_date=_date(item.get("publicationDate")),
            year=item.get("year"),
            work_type=publication_types[0] if publication_types else "article",
            venue=item.get("venue") or "",
            authors=tuple(
                author.get("name", "").strip()
                for author in item.get("authors") or []
                if author.get("name")
            ),
            identifiers=identifiers,
            topics=tuple(item.get("fieldsOfStudy") or ()),
            citation_count=int(item.get("citationCount") or 0),
            reference_count=int(item.get("referenceCount") or len(references)),
            is_open_access=bool(oa.get("url")),
            pdf_url=oa.get("url"),
            landing_url=item.get("url") or "",
            references=references,
            raw_payload=item,
        )
