from __future__ import annotations

import hashlib
import re
from datetime import date

from api.models import Article, WorkVersion
from scholarly.normalize import normalize_arxiv_id, normalize_doi
from scholarly.schema import CanonicalWorkRecord


_ARXIV_VERSION_RE = re.compile(r"v(?P<number>\d+)$", re.IGNORECASE)


def version_type(value: str | None) -> str:
    normalized = (value or "").strip().casefold()
    return {
        "submittedversion": "submitted",
        "submitted": "submitted",
        "acceptedversion": "accepted",
        "accepted": "accepted",
        "publishedversion": "published",
        "published": "published",
    }.get(normalized, "unknown")


def location_external_id(
    doi: str, landing_url: str, pdf_url: str | None, version_label: str
) -> str:
    material = "\n".join((normalize_doi(doi), landing_url, pdf_url or "", version_label))
    return f"{normalize_doi(doi)}:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def upsert_work_version(
    *,
    article: Article,
    source: str,
    external_id: str,
    version_type_value: str,
    version_label: str = "",
    version_number: int | None = None,
    publication_date: date | None = None,
    landing_url: str = "",
    pdf_url: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    is_open_access: bool = False,
    license_value: str = "",
    host_type: str = "",
    oa_status: str = "",
    provenance: dict | None = None,
) -> WorkVersion:
    work_version, _ = WorkVersion.objects.update_or_create(
        source=source,
        external_id=external_id,
        defaults={
            "article": article,
            "version_type": version_type_value,
            "version_label": version_label,
            "version_number": version_number,
            "publication_date": publication_date,
            "landing_url": landing_url,
            "pdf_url": pdf_url,
            "doi": normalize_doi(doi) if doi else None,
            "arxiv_id": normalize_arxiv_id(arxiv_id) if arxiv_id else None,
            "is_open_access": is_open_access,
            "license": license_value,
            "host_type": host_type,
            "oa_status": oa_status,
            "provenance": provenance or {},
        },
    )
    return work_version


def sync_record_version(
    article: Article, record: CanonicalWorkRecord, *, retrieved_at: str
) -> WorkVersion | None:
    if record.source == "arxiv":
        match = _ARXIV_VERSION_RE.search(record.external_id)
        label = match.group(0).lower() if match else ""
        return upsert_work_version(
            article=article,
            source="arxiv",
            external_id=record.external_id.lower(),
            version_type_value="submitted",
            version_label=label,
            version_number=int(match.group("number")) if match else None,
            publication_date=record.publication_date,
            landing_url=record.landing_url,
            pdf_url=record.pdf_url,
            doi=record.identifiers.get("doi"),
            arxiv_id=record.identifiers.get("arxiv"),
            is_open_access=True,
            provenance={
                "provider": record.source,
                "retrieved_at": retrieved_at,
            },
        )
    if record.source == "crossref":
        doi = record.identifiers.get("doi") or record.external_id
        return upsert_work_version(
            article=article,
            source="crossref",
            external_id=normalize_doi(doi),
            version_type_value="published",
            version_label="publishedVersion",
            publication_date=record.publication_date,
            landing_url=record.landing_url,
            pdf_url=record.pdf_url,
            doi=doi,
            is_open_access=record.is_open_access,
            provenance={
                "provider": record.source,
                "retrieved_at": retrieved_at,
            },
        )
    return None
