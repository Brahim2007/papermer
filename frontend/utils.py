from __future__ import annotations

import logging
from collections.abc import Iterable

import requests
from django.conf import settings
from django.db import transaction

from api.models import Article, Authors

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = (5, 30)
MENDELEY_SEARCH_URL = "https://api.mendeley.com/search/catalog"
MENDELEY_TOKEN_URL = "https://api.mendeley.com/oauth/token"


def twitter_from_doi(title: str, doi: str | None) -> list[dict]:
    """Fetch recent public mentions when an X API bearer token is configured."""
    if not settings.TWITTER_BEARER:
        return []
    terms = [f'"{title}"']
    if doi:
        terms.append(f'"{doi}"')
    response = requests.get(
        "https://api.twitter.com/2/tweets/search/recent",
        headers={"Authorization": f"Bearer {settings.TWITTER_BEARER}"},
        params={"query": " OR ".join(terms), "max_results": 10},
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        logger.warning("X search failed with status %s", response.status_code)
        return []
    return response.json().get("data", [])


def get_mendeley_access_token() -> str:
    if not settings.MENDELEY_ID or not settings.MENDELEY_SECRET:
        raise RuntimeError("Mendeley credentials are not configured")
    response = requests.post(
        MENDELEY_TOKEN_URL,
        auth=(settings.MENDELEY_ID, settings.MENDELEY_SECRET),
        data={"grant_type": "client_credentials", "scope": "all"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _author_name(author: dict) -> str:
    explicit = author.get("name")
    if explicit:
        return explicit.strip()
    return " ".join(
        part.strip()
        for part in (author.get("first_name", ""), author.get("last_name", ""))
        if part and part.strip()
    ) or "Anonymous"


def _catalog_link(record: dict) -> str:
    link = record.get("link")
    if isinstance(link, str):
        return link
    if isinstance(link, list) and link:
        candidate = link[0]
        if isinstance(candidate, str):
            return candidate
        if isinstance(candidate, dict):
            return candidate.get("href", "")
    doi = record.get("identifiers", {}).get("doi")
    return f"https://doi.org/{doi}" if doi else ""


@transaction.atomic
def ingest_mendeley_records(records: Iterable[dict]) -> list[str]:
    article_ids: list[str] = []
    for record in records:
        article_id = record.get("id")
        if not article_id or not record.get("title"):
            continue
        year = record.get("year")
        article, created = Article.objects.update_or_create(
            id=article_id,
            defaults={
                "title": record["title"],
                "type": record.get("type", "journal"),
                "year": int(year) if str(year).isdigit() else None,
                "source": record.get("source", ""),
                "publisher": record.get("publisher", ""),
                "identifiers": record.get("identifiers") or {},
                "link": _catalog_link(record),
                "pdf": record.get("pdf"),
                "abstract": record.get("abstract") or "",
                "keywords": (record.get("keywords") or [])[:20],
            },
        )
        if created or record.get("authors"):
            authors = [
                Authors.objects.get_or_create(name=_author_name(author))[0]
                for author in record.get("authors", [])
            ]
            article.authors.set(authors)
        article_ids.append(str(article.pk))
    return article_ids


def get_data_by_query(token: str, query: str, limit: int = 100) -> list[str]:
    if not token:
        raise ValueError("a Mendeley access token is required")
    response = requests.get(
        MENDELEY_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.mendeley-document.1+json",
        },
        params={"query": query, "open_access": "true", "limit": min(limit, 100)},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return ingest_mendeley_records(response.json())


def get_article_from_authors(author: str, token: str, limit: int = 100) -> list[str]:
    if not token:
        raise ValueError("a Mendeley access token is required")
    response = requests.get(
        MENDELEY_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.mendeley-document.1+json",
        },
        params={"author": author, "open_access": "true", "limit": min(limit, 100)},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return ingest_mendeley_records(response.json())


def get_data(token: str, queries: Iterable[str] | None = None) -> list[str]:
    article_ids: list[str] = []
    for query in queries or ():
        article_ids.extend(get_data_by_query(token, query))
    return list(dict.fromkeys(article_ids))
