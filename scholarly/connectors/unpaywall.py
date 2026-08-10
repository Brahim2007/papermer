from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote

from scholarly.normalize import normalize_doi

from .base import BaseConnector, ConnectorRequestError


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class OALocation:
    landing_url: str
    pdf_url: str | None
    host_type: str
    version: str
    license: str
    is_best: bool
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UnpaywallRecord:
    doi: str
    is_open_access: bool
    oa_status: str
    oa_date: date | None
    locations: tuple[OALocation, ...]
    raw_payload: dict[str, Any]


class UnpaywallConnector(BaseConnector):
    source = "unpaywall"
    endpoint = "https://api.unpaywall.org/v2"

    def __init__(
        self, *, email: str, min_interval_seconds: float = 0.2, **kwargs
    ) -> None:
        if not email.strip():
            raise ValueError("Unpaywall requires a contact email")
        super().__init__(min_interval_seconds=min_interval_seconds, **kwargs)
        self.email = email.strip()

    def lookup(self, doi: str) -> UnpaywallRecord | None:
        normalized = normalize_doi(doi)
        try:
            payload = self.get_json(
                f"{self.endpoint}/{quote(normalized, safe='')}",
                params={"email": self.email},
            )
        except ConnectorRequestError as exc:
            if exc.status_code == 404:
                return None
            raise
        best = payload.get("best_oa_location") or {}
        locations = []
        for location in payload.get("oa_locations") or ():
            landing_url = location.get("url_for_landing_page") or location.get("url")
            pdf_url = location.get("url_for_pdf")
            if not landing_url and not pdf_url:
                continue
            locations.append(
                OALocation(
                    landing_url=landing_url or pdf_url,
                    pdf_url=pdf_url,
                    host_type=location.get("host_type") or "",
                    version=location.get("version") or "",
                    license=location.get("license") or "",
                    is_best=bool(best and location == best),
                    raw_payload=location,
                )
            )
        return UnpaywallRecord(
            doi=normalized,
            is_open_access=bool(payload.get("is_oa")),
            oa_status=payload.get("oa_status") or "closed",
            oa_date=_date(payload.get("oa_date")),
            locations=tuple(locations),
            raw_payload=payload,
        )

    def search(self, query: str, *, limit: int = 25):
        raise NotImplementedError("Unpaywall supports DOI lookup, not keyword search")
