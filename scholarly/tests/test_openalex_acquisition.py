import gzip
import json

from api.models import Article
from experiments import acquire_openalex_scope as acquisition


def _spec():
    return {
        "format_version": 3,
        "name": "test",
        "source_format": "openalex_jsonl",
        "from_date": "2020-01-01",
        "to_date": "2025-12-31",
        "target_document_count": 2,
        "require_abstract": True,
        "exclude_retracted": True,
        "languages": ["en"],
        "openalex_work_types": ["article"],
        "include_topics": ["Artificial Intelligence"],
        "include_topic_ids": ["1702"],
        "sampling": {
            "method": "openalex_seeded_stratified_sample_v1",
            "seed": 7,
            "page_size": 1,
            "strata": [
                {
                    "name": "ai_articles",
                    "quota": 2,
                    "seed": 71,
                    "reserve_seeds": [72, 73],
                    "primary_topic_subfield_id": "1702",
                    "work_types": ["article"],
                }
            ],
        },
    }


def _work(number):
    return {
        "id": f"https://openalex.org/W{number}",
        "display_name": f"Paper {number}",
        "publication_date": "2024-01-02",
        "language": "en",
        "type": "article",
        "abstract_inverted_index": {"paper": [0]},
        "is_retracted": False,
        "primary_topic": {
            "id": "https://openalex.org/T10000",
            "display_name": "A narrower topic",
            "subfield": {
                "id": "https://openalex.org/subfields/1702",
                "display_name": "Artificial Intelligence",
            },
        },
    }


def test_canonical_filter_contains_frozen_scope_constraints():
    spec = _spec()
    value = acquisition.canonical_filter(spec, spec["sampling"]["strata"][0])
    assert "from_publication_date:2020-01-01" in value
    assert "to_publication_date:2025-12-31" in value
    assert "primary_topic.subfield.id:1702" in value
    assert "type:article" in value
    assert "has_abstract:true" in value


def test_article_landing_url_capacity_covers_openalex_metadata():
    assert Article._meta.get_field("link").max_length == 500


def test_acquisition_checkpoints_exclude_api_key(monkeypatch, tmp_path):
    spec = _spec()
    spec_raw = json.dumps(spec, sort_keys=True).encode()

    def fake_get_json(_session, params):
        page = int(params["page"])
        return {
            "meta": {"count": 2, "cost_usd": 0.0001},
            "results": [_work(page)],
        }

    monkeypatch.setattr(acquisition, "_get_json", fake_get_json)
    output = tmp_path / "scope.jsonl.gz"
    report = acquisition.acquire(spec, spec_raw, api_key="secret", output=output)

    assert report["document_count"] == 2
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        assert [json.loads(line)["id"] for line in handle] == [
            "https://openalex.org/W1",
            "https://openalex.org/W2",
        ]
    checkpoint_text = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / ".scope.jsonl.gz.pages").rglob("*.json")
    )
    assert "secret" not in checkpoint_text
    assert "api_key" not in checkpoint_text


def test_acquisition_replaces_rejected_records_from_frozen_reserve(monkeypatch, tmp_path):
    spec = _spec()
    spec_raw = json.dumps(spec, sort_keys=True).encode()

    def fake_get_json(_session, params):
        page = int(params["page"])
        seed = int(params["seed"])
        work = _work(page if seed == 71 else page + 2)
        if seed == 71 and page == 1:
            work["display_name"] = ""
        return {"meta": {"count": 2}, "results": [work]}

    monkeypatch.setattr(acquisition, "_get_json", fake_get_json)
    output = tmp_path / "scope.jsonl.gz"
    report = acquisition.acquire(spec, spec_raw, api_key="secret", output=output)

    assert report["document_count"] == 2
    assert report["strata"][0]["rounds_used"] == 2
    assert report["strata"][0]["rejections"] == {"missing_title": 1}
