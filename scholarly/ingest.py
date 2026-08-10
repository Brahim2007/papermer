from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from api.models import (
    Article,
    Authors,
    Citation,
    SourceRecord,
    WorkIdentifier,
)

from .normalize import normalize_identifier, normalize_title
from .schema import CanonicalWorkRecord
from .versions import sync_record_version


class IdentityConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IngestResult:
    article_id: str
    created: bool
    source: str
    external_id: str


FIELD_PRIORITY = {
    "title": {"openalex": 1, "semantic_scholar": 2, "crossref": 3},
    "abstract": {"openalex": 1, "crossref": 2, "semantic_scholar": 3},
    "venue": {"openalex": 1, "semantic_scholar": 2, "crossref": 3},
    "publisher": {"semantic_scholar": 1, "openalex": 2, "crossref": 3},
    "publication_date": {"openalex": 1, "semantic_scholar": 2, "crossref": 3},
}

DIRECT_IDENTIFIER_FIELDS = {
    "doi": "doi",
    "arxiv": "arxiv_id",
    "openalex": "openalex_id",
    "s2": "semantic_scholar_id",
}


def _normalized_identifiers(record: CanonicalWorkRecord) -> dict[str, str]:
    normalized = {}
    for scheme, value in record.identifiers.items():
        if value:
            normalized[scheme.lower()] = normalize_identifier(scheme, value)
    source_scheme = "s2" if record.source == "semantic_scholar" else record.source
    if source_scheme == "crossref":
        normalized.setdefault("doi", normalize_identifier("doi", record.external_id))
    else:
        normalized.setdefault(
            source_scheme,
            normalize_identifier(source_scheme, record.external_id),
        )
    return {scheme: value for scheme, value in normalized.items() if value}


def _find_article(
    record: CanonicalWorkRecord, identifiers: dict[str, str]
) -> Article | None:
    source_record = SourceRecord.objects.filter(
        source=record.source, external_id=record.external_id
    ).select_related("article").first()
    if source_record and source_record.article:
        return source_record.article

    identifier_query = Q()
    for scheme, value in identifiers.items():
        identifier_query |= Q(scheme=scheme, normalized_value=value)
    matched_ids = set(
        WorkIdentifier.objects.filter(identifier_query).values_list(
            "article_id", flat=True
        )
    ) if identifiers else set()
    if len(matched_ids) > 1:
        raise IdentityConflictError(
            f"identifiers map to multiple articles: {sorted(matched_ids)}"
        )
    if matched_ids:
        return Article.objects.get(pk=next(iter(matched_ids)))

    direct_query = {}
    for scheme, field in DIRECT_IDENTIFIER_FIELDS.items():
        if identifiers.get(scheme):
            direct_query[field] = identifiers[scheme]
    for field, value in direct_query.items():
        article = Article.objects.filter(**{field: value}).first()
        if article:
            return article

    normalized = normalize_title(record.title)
    if normalized and record.year:
        candidates = Article.objects.filter(
            normalized_title=normalized, year=record.year
        )[:2]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _should_replace(article: Article, field: str, record: CanonicalWorkRecord) -> bool:
    current = getattr(article, field)
    if current in (None, "", [], {}):
        return True
    previous_source = (article.provenance.get(field) or {}).get("source", "")
    priorities = FIELD_PRIORITY.get(field, {})
    return priorities.get(record.source, 0) > priorities.get(previous_source, 0)


def _set_with_provenance(
    article: Article,
    field: str,
    value,
    record: CanonicalWorkRecord,
    retrieved_at: str,
) -> None:
    if value in (None, "", [], ()) or not _should_replace(article, field, record):
        return
    setattr(article, field, value)
    article.provenance[field] = {
        "source": record.source,
        "external_id": record.external_id,
        "retrieved_at": retrieved_at,
    }


def _stable_article_id(identifiers: dict[str, str], record: CanonicalWorkRecord) -> str:
    for scheme in ("doi", "arxiv", "openalex", "s2"):
        if identifiers.get(scheme):
            key = f"{scheme}:{identifiers[scheme]}"
            return str(uuid.uuid5(uuid.NAMESPACE_URL, key))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{record.source}:{record.external_id}"))


def _sync_authors(article: Article, author_names: tuple[str, ...]) -> None:
    names = list(dict.fromkeys(name.strip() for name in author_names if name.strip()))
    if not names:
        return
    existing_names = set(
        Authors.objects.filter(name__in=names).values_list("name", flat=True)
    )
    Authors.objects.bulk_create(
        [Authors(name=name) for name in names if name not in existing_names],
        ignore_conflicts=True,
    )
    article.authors.add(*Authors.objects.filter(name__in=names))


def _sync_identifiers(
    article: Article,
    identifiers: dict[str, str],
    record: CanonicalWorkRecord,
) -> None:
    if not identifiers:
        return
    query = Q()
    for scheme, value in identifiers.items():
        query |= Q(scheme=scheme, normalized_value=value)
    existing = {
        (identifier.scheme, identifier.normalized_value): identifier
        for identifier in WorkIdentifier.objects.filter(query)
    }
    additions = []
    updates = []
    for scheme, value in identifiers.items():
        identifier = existing.get((scheme, value))
        if identifier and identifier.article_id != article.pk:
            raise IdentityConflictError(
                f"{scheme}:{value} already belongs to {identifier.article_id}"
            )
        raw_value = record.identifiers.get(scheme, value)
        if identifier:
            if identifier.value != raw_value or identifier.source != record.source:
                identifier.value = raw_value
                identifier.source = record.source
                updates.append(identifier)
        else:
            additions.append(
                WorkIdentifier(
                    article=article,
                    scheme=scheme,
                    value=raw_value,
                    normalized_value=value,
                    source=record.source,
                )
            )
    WorkIdentifier.objects.bulk_create(additions, ignore_conflicts=True)
    if updates:
        WorkIdentifier.objects.bulk_update(updates, ["value", "source"])


def _sync_citations(article: Article, record: CanonicalWorkRecord) -> None:
    references = {
        (scheme.lower(), normalize_identifier(scheme, value))
        for scheme, value in record.references
        if value
    }
    references = {pair for pair in references if pair[1]}
    if not references:
        return

    identifier_query = Q()
    for scheme, value in references:
        identifier_query |= Q(scheme=scheme, normalized_value=value)
    cited_articles = {
        (identifier.scheme, identifier.normalized_value): identifier.article
        for identifier in WorkIdentifier.objects.filter(identifier_query).select_related(
            "article"
        )
    }
    existing = {
        (citation.identifier_scheme, citation.cited_identifier): citation
        for citation in Citation.objects.filter(citing_article=article)
    }
    additions = []
    updates = []
    for scheme, value in references:
        cited = cited_articles.get((scheme, value))
        citation = existing.get((scheme, value))
        if citation:
            cited_id = cited.pk if cited else None
            if citation.cited_article_id != cited_id or citation.source != record.source:
                citation.cited_article = cited
                citation.source = record.source
                updates.append(citation)
        else:
            additions.append(
                Citation(
                    citing_article=article,
                    cited_article=cited,
                    identifier_scheme=scheme,
                    cited_identifier=value,
                    source=record.source,
                )
            )
    Citation.objects.bulk_create(additions, ignore_conflicts=True)
    if updates:
        Citation.objects.bulk_update(updates, ["cited_article", "source"])


def _ingest_record(record: CanonicalWorkRecord) -> IngestResult:
    identifiers = _normalized_identifiers(record)
    article = _find_article(record, identifiers)
    created = article is None
    if article is None:
        article = Article(
            id=_stable_article_id(identifiers, record),
            title=record.title.strip(),
            normalized_title=normalize_title(record.title),
            abstract="",
            type=record.work_type or "article",
            year=record.year,
            source=record.venue,
            publisher=record.publisher,
            identifiers={},
            link=record.landing_url,
            pdf=record.pdf_url,
            provenance={},
        )

    retrieved = timezone.now()
    retrieved_at = retrieved.isoformat()
    article.provenance = dict(article.provenance or {})
    _set_with_provenance(article, "title", record.title.strip(), record, retrieved_at)
    _set_with_provenance(article, "abstract", record.abstract.strip(), record, retrieved_at)
    _set_with_provenance(article, "venue", record.venue, record, retrieved_at)
    _set_with_provenance(article, "publisher", record.publisher, record, retrieved_at)
    _set_with_provenance(
        article, "publication_date", record.publication_date, record, retrieved_at
    )
    _set_with_provenance(article, "language", record.language, record, retrieved_at)
    article.normalized_title = normalize_title(article.title)
    article.year = article.year or record.year
    article.type = article.type or record.work_type or "article"
    article.source = article.source or record.venue
    article.link = article.link or record.landing_url
    article.pdf = article.pdf or record.pdf_url
    article.citation_count = max(article.citation_count, record.citation_count)
    article.reference_count = max(article.reference_count, record.reference_count)
    article.is_retracted = article.is_retracted or record.is_retracted
    article.is_open_access = article.is_open_access or record.is_open_access
    article.keywords = sorted(set(article.keywords or ()) | set(record.keywords))
    article.topics = sorted(set(article.topics or ()) | set(record.topics))
    article.identifiers.pop("crossref", None)
    article.identifiers = {**(article.identifiers or {}), **identifiers}
    for scheme, field in DIRECT_IDENTIFIER_FIELDS.items():
        if identifiers.get(scheme) and not getattr(article, field):
            setattr(article, field, identifiers[scheme])
    article.save()

    _sync_authors(article, record.authors)
    _sync_identifiers(article, identifiers, record)

    canonical_payload = json.dumps(
        record.raw_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    SourceRecord.objects.update_or_create(
        source=record.source,
        external_id=record.external_id,
        defaults={
            "article": article,
            "payload": record.raw_payload,
            "payload_checksum": hashlib.sha256(
                canonical_payload.encode("utf-8")
            ).hexdigest(),
            "retrieved_at": retrieved,
        },
    )

    sync_record_version(article, record, retrieved_at=retrieved_at)
    _sync_citations(article, record)
    return IngestResult(
        article_id=str(article.pk),
        created=created,
        source=record.source,
        external_id=record.external_id,
    )


@transaction.atomic
def ingest_record(record: CanonicalWorkRecord) -> IngestResult:
    return _ingest_record(record)


@transaction.atomic
def ingest_records(records: list[CanonicalWorkRecord]) -> list[IngestResult]:
    return [_ingest_record(record) for record in records]
