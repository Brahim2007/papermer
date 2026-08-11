import gzip
import json
from pathlib import Path

import pytest
from django.core.management import call_command

from scholarly.snapshot import (
    deterministic_sample,
    iter_jsonl,
    openalex_scope_rejection,
    validate_bulk_scope,
)


def _spec():
    return {
        "format_version": 3,
        "name": "test",
        "source_format": "openalex_jsonl",
        "from_date": "2020-01-01",
        "to_date": "2025-12-31",
        "target_document_count": 1,
        "require_abstract": True,
        "exclude_retracted": True,
        "languages": ["en"],
        "openalex_work_types": ["article"],
        "include_topics": ["Information retrieval"],
        "sampling": {
            "method": "deterministic_sha256_bottom_k",
            "seed": "fixed",
        },
    }


def _work():
    return {
        "id": "https://openalex.org/W1",
        "display_name": "A paper",
        "publication_date": "2024-01-02",
        "language": "en",
        "type": "article",
        "abstract_inverted_index": {"abstract": [0]},
        "topics": [{"display_name": "Information retrieval"}],
        "is_retracted": False,
    }


def test_openalex_scope_accepts_matching_work():
    assert openalex_scope_rejection(_work(), _spec()) is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"language": "fr"}, "language"),
        ({"publication_date": "2019-12-31"}, "outside_date_range"),
        ({"abstract_inverted_index": None}, "missing_abstract"),
        ({"is_retracted": True}, "retracted"),
        ({"topics": [{"display_name": "Medicine"}]}, "topic"),
    ],
)
def test_openalex_scope_rejection_codes(change, reason):
    work = {**_work(), **change}
    assert openalex_scope_rejection(work, _spec()) == reason


def test_iter_jsonl_supports_gzip_and_resume(tmp_path: Path):
    path = tmp_path / "snapshot.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "W1"}) + "\n")
        handle.write(json.dumps({"id": "W2"}) + "\n")
    assert list(iter_jsonl(path, skip_lines=1)) == [(2, {"id": "W2"})]


def test_bulk_scope_requires_neutral_sampling():
    spec = _spec()
    spec["sampling"] = {"method": "top_cited", "seed": "fixed"}
    with pytest.raises(ValueError, match="deterministic_sha256_bottom_k"):
        validate_bulk_scope(spec)


def test_deterministic_sample_is_order_independent_and_not_citation_ranked():
    spec = _spec()
    spec["target_document_count"] = 2
    works = []
    for number, citations in ((1, 9999), (2, 10), (3, 0), (4, 500)):
        work = _work()
        work["id"] = f"https://openalex.org/W{number}"
        work["cited_by_count"] = citations
        works.append(work)
    forward, _ = deterministic_sample(iter(works), spec=spec)
    reverse, _ = deterministic_sample(iter(reversed(works)), spec=spec)
    assert [item["id"] for item in forward] == [item["id"] for item in reverse]
    assert len(forward) == 2


def test_snapshot_import_command_dry_run_writes_pinned_report(tmp_path: Path):
    spec_path = tmp_path / "spec.json"
    input_path = tmp_path / "selected.jsonl"
    output_path = tmp_path / "report.json"
    spec_path.write_text(json.dumps(_spec()), encoding="utf-8")
    input_path.write_text(json.dumps(_work()) + "\n", encoding="utf-8")

    call_command(
        "import_scholarly_snapshot",
        input=[input_path],
        spec=spec_path,
        output=output_path,
        batch_size=1,
        dry_run=True,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["target_check"]["met"] is True
    assert report["totals"] == {
        "eligible": 1,
        "created": 0,
        "updated": 0,
        "identity_conflicts": 0,
    }
    assert len(report["signature"]["inputs"][str(input_path.resolve())]) == 64
