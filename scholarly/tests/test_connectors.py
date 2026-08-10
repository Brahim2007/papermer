import pytest
from datetime import date

from scholarly.connectors import (
    ArxivConnector,
    CrossrefConnector,
    OpenAlexConnector,
    SemanticScholarConnector,
    UnpaywallConnector,
)
from scholarly.normalize import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
    normalize_title,
)


def test_identifier_normalization():
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_arxiv_id("arXiv:2401.12345v2") == "2401.12345"
    assert normalize_openalex_id("https://openalex.org/W123") == "W123"
    assert normalize_title("  Hybrid—Retrieval! ") == "hybrid retrieval"


def test_semantic_scholar_default_rate_is_below_one_request_per_second():
    connector = SemanticScholarConnector(api_key="test")
    assert connector.min_interval_seconds == 1.1
    with pytest.raises(ValueError, match="non-negative"):
        SemanticScholarConnector(api_key="test", min_interval_seconds=-0.1)


def test_openalex_mapping_reconstructs_abstract():
    record = OpenAlexConnector()._record(
        {
            "id": "https://openalex.org/W123",
            "display_name": "Hybrid Retrieval",
            "publication_year": 2024,
            "publication_date": "2024-05-01",
            "doi": "https://doi.org/10.1/TEST",
            "ids": {},
            "abstract_inverted_index": {"retrieval": [1], "Hybrid": [0]},
            "authorships": [{"author": {"display_name": "Ada Author"}}],
            "topics": [{"display_name": "Information Retrieval"}],
            "referenced_works": ["https://openalex.org/W99"],
            "primary_location": {"source": {"display_name": "IR Journal"}},
            "open_access": {"is_oa": True},
        }
    )
    assert record.external_id == "W123"
    assert record.abstract == "Hybrid retrieval"
    assert record.identifiers["doi"] == "10.1/test"
    assert record.references == (("openalex", "W99"),)


def test_openalex_scoped_search_sends_frozen_filters(monkeypatch):
    connector = OpenAlexConnector(email="research@example.org")
    observed = {}

    def fake_get_json(url, *, params=None, headers=None):
        observed.update(params)
        return {"results": []}

    monkeypatch.setattr(connector, "get_json", fake_get_json)
    connector.search_scoped(
        "paper recommendation",
        from_date=date(2020, 1, 1),
        to_date=date(2024, 12, 31),
        limit=20,
        work_types=("article", "review"),
        languages=("en",),
        require_abstract=True,
    )
    assert "from_publication_date:2020-01-01" in observed["filter"]
    assert "to_publication_date:2024-12-31" in observed["filter"]
    assert "has_abstract:true" in observed["filter"]
    assert observed["per-page"] == 20


def test_semantic_scholar_mapping():
    record = SemanticScholarConnector()._record(
        {
            "paperId": "s2-id",
            "title": "Scientific Search",
            "abstract": "An abstract",
            "year": 2025,
            "externalIds": {"DOI": "10.2/TEST", "ArXiv": "2501.00001v1"},
            "authors": [{"name": "Researcher"}],
            "fieldsOfStudy": ["Computer Science"],
            "citationCount": 7,
            "referenceCount": 1,
            "references": [{"paperId": "cited-id"}],
        }
    )
    assert record.identifiers == {
        "s2": "s2-id",
        "doi": "10.2/test",
        "arxiv": "2501.00001",
    }
    assert record.references == (("s2", "cited-id"),)


def test_crossref_mapping():
    record = CrossrefConnector()._record(
        {
            "DOI": "10.3/TEST",
            "title": ["A Canonical Paper"],
            "author": [{"given": "A", "family": "Researcher"}],
            "published-online": {"date-parts": [[2024, 3, 2]]},
            "container-title": ["Journal"],
            "publisher": "Publisher",
            "type": "journal-article",
            "reference": [{"DOI": "10.4/CITED"}],
            "is-referenced-by-count": 3,
        }
    )
    assert record.publication_date.isoformat() == "2024-03-02"
    assert record.identifiers["doi"] == "10.3/test"
    assert record.references == (("doi", "10.4/cited"),)


def test_arxiv_mapping_keeps_version_and_links_published_doi(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/cs/9901001v2</id>
        <updated>2000-01-03T00:00:00Z</updated>
        <published>1999-01-02T00:00:00Z</published>
        <title>Version-aware scholarly retrieval</title>
        <summary>A canonical abstract.</summary>
        <author><name>Ada Author</name></author>
        <category term="cs.IR"/>
        <arxiv:doi>10.1000/EXAMPLE</arxiv:doi>
        <link href="https://arxiv.org/abs/cs/9901001v2"
              rel="alternate" type="text/html"/>
        <link href="https://arxiv.org/pdf/cs/9901001v2"
              rel="related" type="application/pdf" title="pdf"/>
      </entry>
    </feed>"""
    connector = ArxivConnector(min_interval_seconds=0)
    monkeypatch.setattr(connector, "get_text", lambda *args, **kwargs: xml)
    record = connector.lookup("cs/9901001")
    assert record is not None
    assert record.external_id == "cs/9901001v2"
    assert record.identifiers == {
        "arxiv": "cs/9901001",
        "doi": "10.1000/example",
    }
    assert record.publication_date == date(1999, 1, 2)
    assert record.pdf_url == "https://arxiv.org/pdf/cs/9901001v2"


def test_arxiv_scoped_search_sends_frozen_date_and_categories(monkeypatch):
    connector = ArxivConnector(min_interval_seconds=0)
    observed = {}

    def fake_query(params):
        observed.update(params)
        return []

    monkeypatch.setattr(connector, "_query", fake_query)
    connector.search_scoped(
        "scientific paper recommendation",
        from_date=date(2015, 1, 1),
        to_date=date(2026, 8, 4),
        limit=50,
        categories=("cs.IR", "cs.DL"),
    )
    assert "submittedDate:[201501010000 TO 202608042359]" in observed[
        "search_query"
    ]
    assert "(cat:cs.IR OR cat:cs.DL)" in observed["search_query"]
    assert observed["sortBy"] == "relevance"
    assert observed["max_results"] == 50


def test_unpaywall_mapping_marks_best_location(monkeypatch):
    connector = UnpaywallConnector(
        email="research@example.org", min_interval_seconds=0
    )
    best = {
        "url_for_landing_page": "https://repository.example/paper",
        "url_for_pdf": "https://repository.example/paper.pdf",
        "host_type": "repository",
        "version": "acceptedVersion",
        "license": "cc-by",
    }
    monkeypatch.setattr(
        connector,
        "get_json",
        lambda *args, **kwargs: {
            "doi": "10.1000/example",
            "is_oa": True,
            "oa_status": "green",
            "oa_date": "2024-01-02",
            "best_oa_location": best,
            "oa_locations": [best],
        },
    )
    record = connector.lookup("https://doi.org/10.1000/EXAMPLE")
    assert record is not None
    assert record.doi == "10.1000/example"
    assert record.oa_status == "green"
    assert record.oa_date == date(2024, 1, 2)
    assert record.locations[0].version == "acceptedVersion"
    assert record.locations[0].is_best is True
