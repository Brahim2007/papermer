"""Validate adjudication and freeze graded qrels with provenance."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--agreement-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    rows = []
    seen = set()
    unresolved = []
    with args.adjudication.open(encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            query_id = str(row.get("query_id", "")).strip()
            document_id = str(row.get("document_id", "")).strip()
            raw_relevance = str(row.get("final_relevance", "")).strip()
            key = (query_id, document_id)
            if not query_id or not document_id or key in seen:
                raise ValueError(f"invalid or duplicate item at line {line_number}")
            seen.add(key)
            if not raw_relevance:
                unresolved.append(key)
                continue
            relevance = int(raw_relevance)
            if relevance not in {0, 1, 2}:
                raise ValueError(f"invalid relevance at line {line_number}")
            if (
                row.get("agreement_status") == "conflict"
                and not str(row.get("adjudication_rationale", "")).strip()
            ):
                raise ValueError(
                    f"conflict at line {line_number} requires adjudication_rationale"
                )
            rows.append((query_id, document_id, relevance))
    if unresolved:
        raise ValueError(f"{len(unresolved)} judgments remain unresolved")
    agreement = json.loads(args.agreement_report.read_text(encoding="utf-8"))
    if agreement.get("unique_item_count") != len(rows):
        raise ValueError("agreement report item count does not match adjudication")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["query_id", "document_id", "relevance"])
        writer.writerows(sorted(rows))
    manifest_path = args.manifest or args.output.with_suffix(".manifest.json")
    manifest = {
        "format_version": 1,
        "scale": {"0": "not relevant", "1": "partially relevant", "2": "directly relevant"},
        "adjudication_path": str(args.adjudication),
        "adjudication_sha256": file_sha256(args.adjudication),
        "agreement_report_path": str(args.agreement_report),
        "agreement_report_sha256": file_sha256(args.agreement_report),
        "qrels_path": str(args.output),
        "qrels_sha256": file_sha256(args.output),
        "judgment_count": len(rows),
        "query_count": len({row[0] for row in rows}),
        "agreement": {
            "assessor_count": agreement.get("assessor_count"),
            "conflict_count": agreement.get("conflict_count"),
            "krippendorff_alpha_interval": agreement.get(
                "krippendorff_alpha_interval"
            ),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Frozen {len(rows)} graded judgments to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
