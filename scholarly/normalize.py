from __future__ import annotations

import re
import unicodedata


_SPACE_RE = re.compile(r"\s+")
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(character if character.isalnum() else " " for character in value)
    return _SPACE_RE.sub(" ", value).strip()


def normalize_doi(value: str) -> str:
    normalized = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized.strip()


def normalize_arxiv_id(value: str) -> str:
    normalized = value.strip()
    for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/", "arxiv:"):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
    return _ARXIV_VERSION_RE.sub("", normalized).strip().lower()


def normalize_openalex_id(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1].upper()


def normalize_s2_id(value: str) -> str:
    return value.strip()


NORMALIZERS = {
    "doi": normalize_doi,
    "arxiv": normalize_arxiv_id,
    "openalex": normalize_openalex_id,
    "s2": normalize_s2_id,
    "pmid": lambda value: value.strip(),
}


def normalize_identifier(scheme: str, value: str) -> str:
    normalizer = NORMALIZERS.get(scheme.lower(), lambda item: item.strip())
    return normalizer(value)
