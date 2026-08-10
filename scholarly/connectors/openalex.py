from __future__ import annotations

from datetime import date
from typing import Any

from scholarly.normalize import normalize_doi, normalize_openalex_id, normalize_title
from scholarly.schema import CanonicalWorkRecord

from .base import BaseConnector, ConnectorRequestError


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positioned = [
        (position, token)
        for token, positions in index.items()
        for position in positions
    ]
    return " ".join(token for _, token in sorted(positioned))


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class OpenAlexConnector(BaseConnector):
    source = "openalex"
    endpoint = "https://api.openalex.org/works"

    def __init__(self, *, email: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.email = email

    def search(self, query: str, *, limit: int = 25) -> list[CanonicalWorkRecord]:
        payload = self.get_json(
            self.endpoint,
            params={
                "search": query,
                "per-page": min(limit, 100),
                **({"mailto": self.email} if self.email else {}),
            },
        )
        return [self._record(item) for item in payload.get("results", [])]

    def search_scoped(
        self,
        query: str,
        *,
        from_date: date,
        to_date: date,
        limit: int,
        work_types: tuple[str, ...] = (),
        languages: tuple[str, ...] = (),
        require_abstract: bool = False,
        sort: str = "cited_by_count:desc",
    ) -> list[CanonicalWorkRecord]:
        filters = [
            f"from_publication_date:{from_date.isoformat()}",
            f"to_publication_date:{to_date.isoformat()}",
        ]
        if work_types:
            filters.append(f"type:{'|'.join(work_types)}")
        if languages:
            filters.append(f"language:{'|'.join(languages)}")
        if require_abstract:
            filters.append("has_abstract:true")
        payload = self.get_json(
            self.endpoint,
            params={
                "search": query,
                "filter": ",".join(filters),
                "sort": sort,
                "per-page": min(limit, 100),
                **({"mailto": self.email} if self.email else {}),
            },
        )
        return [self._record(item) for item in payload.get("results", [])]

    def lookup(
        self,
        *,
        openalex_id: str = "",
        doi: str = "",
        title: str = "",
        year: int | None = None,
    ) -> CanonicalWorkRecord | None:
        if openalex_id:
            identifier = normalize_openalex_id(openalex_id)
            try:
                return self._record(
                    self.get_json(
                        f"{self.endpoint}/{identifier}",
                        params={"mailto": self.email} if self.email else None,
                    )
                )
            except ConnectorRequestError as exc:
                if exc.status_code == 404:
                    return None
                raise
        params: dict[str, str | int] = {
            "per-page": 5,
            **({"mailto": self.email} if self.email else {}),
        }
        if doi:
            params["filter"] = f"doi:https://doi.org/{normalize_doi(doi)}"
        elif title:
            params["search"] = title
        else:
            return None
        payload = self.get_json(self.endpoint, params=params)
        candidates = [self._record(item) for item in payload.get("results", [])]
        if doi:
            normalized_doi = normalize_doi(doi)
            return next(
                (
                    record
                    for record in candidates
                    if record.identifiers.get("doi") == normalized_doi
                ),
                None,
            )
        normalized_title = normalize_title(title)
        return next(
            (
                record
                for record in candidates
                if normalize_title(record.title) == normalized_title
                and (year is None or record.year == year)
            ),
            None,
        )

    def _record(self, item: dict[str, Any]) -> CanonicalWorkRecord:
        ids = item.get("ids") or {}
        identifiers: dict[str, str] = {
            "openalex": normalize_openalex_id(item["id"])
        }
        if ids.get("doi") or item.get("doi"):
            identifiers["doi"] = normalize_doi(ids.get("doi") or item["doi"])
        if ids.get("pmid"):
            identifiers["pmid"] = ids["pmid"].rstrip("/").rsplit("/", 1)[-1]

        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        authors = tuple(
            authorship.get("author", {}).get("display_name", "").strip()
            for authorship in item.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        )
        topics = tuple(
            topic.get("display_name", "")
            for topic in item.get("topics", item.get("concepts", []))
            if topic.get("display_name")
        )
        references = tuple(
            ("openalex", normalize_openalex_id(reference))
            for reference in item.get("referenced_works", [])
        )
        oa = item.get("open_access") or {}
        best_oa = item.get("best_oa_location") or {}
        return CanonicalWorkRecord(
            source=self.source,
            external_id=identifiers["openalex"],
            title=item.get("display_name") or item.get("title") or "Untitled",
            abstract=_abstract_from_inverted_index(item.get("abstract_inverted_index")),
            publication_date=_date(item.get("publication_date")),
            year=item.get("publication_year"),
            work_type=item.get("type") or "article",
            venue=source.get("display_name") or "",
            publisher=source.get("host_organization_name") or "",
            language=item.get("language") or "",
            authors=authors,
            identifiers=identifiers,
            topics=topics,
            citation_count=int(item.get("cited_by_count") or 0),
            reference_count=len(references),
            is_retracted=bool(item.get("is_retracted")),
            is_open_access=bool(oa.get("is_oa")),
            pdf_url=best_oa.get("pdf_url"),
            landing_url=location.get("landing_page_url") or item.get("id") or "",
            references=references,
            raw_payload=item,
        )
