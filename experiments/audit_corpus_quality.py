"""Create a reproducible quality gate for a scholarly corpus snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from experiments.build_temporal_benchmark import file_sha256
from retrieval import load_citation_graph
from scholarly.normalize import normalize_title


REQUIRED_COLUMNS = {
    "id",
    "title",
    "abstract",
    "publication_date",
    "year",
    "doi",
    "citation_count",
    "is_retracted",
    "retrieval_text",
}


def _nonempty_rate(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].astype(str).str.strip().ne("").mean())


def audit_corpus(
    corpus: pd.DataFrame,
    *,
    as_of_date: date,
    minimum_abstract_rate: float,
    minimum_doi_rate: float,
    minimum_retrieval_text_rate: float,
    graph_path: Path | None = None,
) -> dict:
    missing_columns = sorted(REQUIRED_COLUMNS - set(corpus.columns))
    if missing_columns:
        raise ValueError(f"corpus is missing required columns: {missing_columns}")
    corpus = corpus.fillna("").copy()
    document_count = len(corpus)
    if document_count == 0:
        raise ValueError("corpus must not be empty")

    identifiers = corpus["id"].astype(str).str.strip()
    normalized_doi = corpus["doi"].astype(str).str.strip().str.lower()
    normalized_titles = corpus["title"].astype(str).map(normalize_title)
    years = pd.to_numeric(corpus["year"], errors="coerce")
    parsed_dates = pd.to_datetime(corpus["publication_date"], errors="coerce")
    future_dates = int(
        (parsed_dates.dt.date > as_of_date).fillna(False).sum()
    )
    completeness = {
        column: _nonempty_rate(corpus, column)
        for column in (
            "title",
            "abstract",
            "publication_date",
            "doi",
            "retrieval_text",
        )
    }
    nonempty_doi = normalized_doi[normalized_doi.ne("")]
    title_year = pd.DataFrame(
        {"title": normalized_titles, "year": years}
    )
    title_year = title_year[
        title_year["title"].ne("") & title_year["year"].notna()
    ]

    graph = None
    if graph_path is not None:
        artifact = load_citation_graph(graph_path)
        corpus_ids = set(identifiers)
        citing = {
            edge.citing_document_id
            for edge in artifact.edges
            if edge.citing_document_id in corpus_ids
        }
        internal = [
            edge
            for edge in artifact.edges
            if edge.cited_document_id in corpus_ids
        ]
        graph = {
            "path": str(graph_path),
            "sha256": file_sha256(graph_path),
            "manifest": artifact.metadata,
            "documents_with_outgoing_references": len(citing),
            "outgoing_document_coverage": len(citing) / document_count,
            "internal_edge_count": len(internal),
            "internal_edge_rate": (
                len(internal) / len(artifact.edges) if artifact.edges else 0.0
            ),
        }

    violations = []
    checks = {
        "abstract_completeness": (
            completeness["abstract"],
            minimum_abstract_rate,
        ),
        "doi_completeness": (completeness["doi"], minimum_doi_rate),
        "retrieval_text_completeness": (
            completeness["retrieval_text"],
            minimum_retrieval_text_rate,
        ),
    }
    for name, (observed, minimum) in checks.items():
        if observed < minimum:
            violations.append(
                {
                    "check": name,
                    "observed": observed,
                    "minimum": minimum,
                }
            )
    hard_counts = {
        "blank_ids": int(identifiers.eq("").sum()),
        "duplicate_ids": int(identifiers.duplicated(keep=False).sum()),
        "invalid_publication_dates": int(parsed_dates.isna().sum()),
        "future_publication_dates": future_dates,
        "unexplained_missing_abstracts": int(
            (
                corpus["abstract"].astype(str).str.strip().eq("")
                & (
                    corpus.get(
                        "abstract_enrichment",
                        pd.Series("", index=corpus.index),
                    )
                    .astype(str)
                    .str.strip()
                    .isin({"", "{}"})
                )
            ).sum()
        ),
    }
    for name, count in hard_counts.items():
        if count:
            violations.append({"check": name, "observed": count, "maximum": 0})

    return {
        "protocol": "scholarly_corpus_quality_gate",
        "as_of_date": as_of_date.isoformat(),
        "status": "pass" if not violations else "fail",
        "document_count": document_count,
        "completeness": completeness,
        "duplicates": {
            "id_rows": hard_counts["duplicate_ids"],
            "doi_rows": int(nonempty_doi.duplicated(keep=False).sum()),
            "normalized_title_year_rows": int(
                title_year.duplicated(["title", "year"], keep=False).sum()
            ),
        },
        "temporal": {
            "invalid_publication_dates": hard_counts[
                "invalid_publication_dates"
            ],
            "future_publication_dates": future_dates,
            "minimum_year": int(years.min()) if years.notna().any() else None,
            "maximum_year": int(years.max()) if years.notna().any() else None,
        },
        "distributions": {
            column: {
                str(key): int(value)
                for key, value in corpus[column]
                .astype(str)
                .replace("", "unknown")
                .value_counts()
                .head(25)
                .items()
            }
            for column in ("source", "language", "type", "is_retracted")
            if column in corpus
        },
        "citation_graph": graph,
        "thresholds": {
            "minimum_abstract_rate": minimum_abstract_rate,
            "minimum_doi_rate": minimum_doi_rate,
            "minimum_retrieval_text_rate": minimum_retrieval_text_rate,
        },
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--citation-graph", type=Path)
    parser.add_argument("--as-of-date", type=date.fromisoformat, required=True)
    parser.add_argument("--minimum-abstract-rate", type=float, default=0.8)
    parser.add_argument("--minimum-doi-rate", type=float, default=0.5)
    parser.add_argument("--minimum-retrieval-text-rate", type=float, default=0.99)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on-violation", action="store_true")
    args = parser.parse_args()

    corpus_hash = file_sha256(args.corpus)
    if args.citation_graph:
        graph_metadata = load_citation_graph(args.citation_graph).metadata
        if graph_metadata.get("corpus_sha256") != corpus_hash:
            raise ValueError("citation graph was built from a different corpus")
    report = audit_corpus(
        pd.read_csv(args.corpus),
        as_of_date=args.as_of_date,
        minimum_abstract_rate=args.minimum_abstract_rate,
        minimum_doi_rate=args.minimum_doi_rate,
        minimum_retrieval_text_rate=args.minimum_retrieval_text_rate,
        graph_path=args.citation_graph,
    )
    report["corpus_path"] = str(args.corpus)
    report["corpus_sha256"] = corpus_hash
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"status": report["status"], "violations": report["violations"]},
            indent=2,
        )
    )
    return 2 if args.fail_on_violation and report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
