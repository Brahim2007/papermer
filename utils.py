"""Maintenance utilities.

This module intentionally performs no network calls at import time.
"""

from __future__ import annotations

from api.models import Authors
from frontend.utils import get_article_from_authors


def ingest_pending_authors(token: str) -> int:
    processed = 0
    for author in Authors.objects.filter(done=False).iterator():
        get_article_from_authors(author.name, token)
        author.done = True
        author.save(update_fields=["done"])
        processed += 1
    return processed
