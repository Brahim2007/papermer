"""Validated, reproducible filters shared by live and fallback search."""

from __future__ import annotations

import json
from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet


FILTER_KEYS = ("year_from", "year_to", "paper_type", "source", "open_access", "min_citations")


def _bounded_int(raw, *, name: str, minimum: int, maximum: int) -> int | None:
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValidationError(f"{name} must be between {minimum} and {maximum}")
    return value


def parse_search_filters(params, *, strict: bool = True) -> dict:
    """Return a canonical JSON-safe filter object from a QueryDict-like mapping."""
    try:
        current_year = date.today().year + 1
        year_from = _bounded_int(
            params.get("year_from"), name="year_from", minimum=1900, maximum=current_year
        )
        year_to = _bounded_int(
            params.get("year_to"), name="year_to", minimum=1900, maximum=current_year
        )
        min_citations = _bounded_int(
            params.get("min_citations"),
            name="min_citations",
            minimum=0,
            maximum=10_000_000,
        )
        if year_from and year_to and year_from > year_to:
            raise ValidationError("year_from must not exceed year_to")
        paper_type = str(params.get("paper_type") or "").strip()[:100]
        source = str(params.get("source") or "").strip()[:150]
        open_access = str(params.get("open_access") or "").strip().lower() in {
            "1",
            "true",
            "on",
            "yes",
        }
    except ValidationError:
        if strict:
            raise
        return {}

    filters = {}
    if year_from is not None:
        filters["year_from"] = year_from
    if year_to is not None:
        filters["year_to"] = year_to
    if paper_type:
        filters["paper_type"] = paper_type
    if source:
        filters["source"] = source
    if open_access:
        filters["open_access"] = True
    if min_citations is not None:
        filters["min_citations"] = min_citations
    return filters


def apply_search_filters(queryset: QuerySet, filters: dict) -> QuerySet:
    if "year_from" in filters:
        queryset = queryset.filter(year__gte=filters["year_from"])
    if "year_to" in filters:
        queryset = queryset.filter(year__lte=filters["year_to"])
    if filters.get("paper_type"):
        queryset = queryset.filter(type__iexact=filters["paper_type"])
    if filters.get("source"):
        queryset = queryset.filter(
            Q(source__iexact=filters["source"]) | Q(venue__iexact=filters["source"])
        )
    if filters.get("open_access"):
        queryset = queryset.filter(is_open_access=True)
    if "min_citations" in filters:
        queryset = queryset.filter(citation_count__gte=filters["min_citations"])
    return queryset


def canonical_filter_key(filters: dict) -> str:
    return json.dumps(filters, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
