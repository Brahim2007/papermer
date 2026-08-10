"""Select deterministic, temporally eligible seed papers across strata."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

from experiments.build_temporal_benchmark import parse_date
from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--from-date", type=date.fromisoformat, required=True)
    parser.add_argument("--to-date", type=date.fromisoformat, required=True)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument(
        "--require-term",
        action="append",
        default=[],
        help="Require this literal phrase in retrieval_text; repeat for multiple phrases.",
    )
    parser.add_argument(
        "--exclude-term",
        action="append",
        default=[],
        help="Exclude this literal phrase from retrieval_text.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1:
        raise ValueError("--count must be positive")
    if args.to_date < args.from_date:
        raise ValueError("--to-date must not precede --from-date")

    corpus = pd.read_csv(args.corpus).fillna("")
    corpus["_publication_date"] = [
        parse_date(str(row.get("publication_date", "")), str(row.get("year", "")))
        for _, row in corpus.iterrows()
    ]
    truthy = {"true", "1", "yes"}
    if "is_retracted" in corpus:
        corpus = corpus[
            ~corpus["is_retracted"].astype(str).str.lower().isin(truthy)
        ]
    eligible = corpus[
        (corpus["_publication_date"] >= args.from_date)
        & (corpus["_publication_date"] <= args.to_date)
        & corpus["title"].astype(str).str.strip().ne("")
        & corpus["abstract"].astype(str).str.strip().ne("")
    ].copy()
    for term in args.require_term:
        eligible = eligible[
            eligible["retrieval_text"]
            .astype(str)
            .str.contains(term, case=False, regex=False)
        ]
    for term in args.exclude_term:
        eligible = eligible[
            ~eligible["retrieval_text"]
            .astype(str)
            .str.contains(term, case=False, regex=False)
        ]
    if len(eligible) < args.count:
        raise ValueError(
            f"only {len(eligible)} eligible papers have title and abstract"
        )

    citations = pd.to_numeric(eligible.get("citation_count", 0), errors="coerce").fillna(0)
    eligible["_popularity"] = pd.qcut(
        citations.rank(method="first"),
        q=min(3, len(eligible)),
        labels=False,
        duplicates="drop",
    )
    eligible["_stratum"] = [
        f"year={published.year};popularity={int(popularity)}"
        for published, popularity in zip(
            eligible["_publication_date"], eligible["_popularity"], strict=True
        )
    ]
    eligible["_random_key"] = [
        hashlib.sha256(f"{args.seed}:{document_id}".encode()).hexdigest()
        for document_id in eligible["id"].astype(str)
    ]
    groups = {
        stratum: group.sort_values("_random_key").to_dict("records")
        for stratum, group in eligible.groupby("_stratum")
    }
    selected = []
    while len(selected) < args.count:
        progressed = False
        for stratum in sorted(groups):
            if groups[stratum] and len(selected) < args.count:
                selected.append(groups[stratum].pop(0))
                progressed = True
        if not progressed:
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "query_id",
        "task_type",
        "seed_id",
        "seed_title",
        "seed_abstract",
        "seed_publication_date",
        "stratum",
        "author_id",
        "query",
        "query_date",
        "notes",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(selected, start=1):
            writer.writerow(
                {
                    "query_id": f"related-{index:04d}",
                    "task_type": "related_paper",
                    "seed_id": row["id"],
                    "seed_title": row["title"],
                    "seed_abstract": row["abstract"],
                    "seed_publication_date": row["_publication_date"].isoformat(),
                    "stratum": row["_stratum"],
                    "author_id": "",
                    "query": "",
                    "query_date": "",
                    "notes": "",
                }
            )
    print(f"Wrote {len(selected)} stratified seed tasks to {args.output}")
    manifest = {
        "format_version": 1,
        "corpus_sha256": file_sha256(args.corpus),
        "output_sha256": file_sha256(args.output),
        "count": len(selected),
        "from_date": args.from_date.isoformat(),
        "to_date": args.to_date.isoformat(),
        "randomization_seed": args.seed,
        "require_terms": args.require_term,
        "exclude_terms": args.exclude_term,
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
