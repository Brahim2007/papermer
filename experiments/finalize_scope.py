"""Validate and freeze a completed scoped-corpus acquisition."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from experiments.build_temporal_benchmark import file_sha256
from retrieval.specter_cache import load_specter2_cache


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--acquisition", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--graph-manifest", type=Path, required=True)
    parser.add_argument("--specter-cache", type=Path, required=True)
    parser.add_argument("--arxiv-audit", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on-violation", action="store_true")
    args = parser.parse_args()

    registration = _json(args.registration)
    acquisition = _json(args.acquisition)
    corpus_manifest = _json(args.corpus_manifest)
    graph_manifest = _json(args.graph_manifest)
    arxiv_audit = _json(args.arxiv_audit)
    quality = _json(args.quality_report)
    cache = load_specter2_cache(args.specter_cache)
    violations = []

    scope_path = Path(registration["scope_spec"])
    scope_hash = file_sha256(scope_path)
    if scope_hash != registration["scope_spec_sha256"]:
        violations.append("scope spec hash differs from preregistration")
    if acquisition.get("spec_sha256") != scope_hash:
        violations.append("acquisition used a different scope spec")
    terminal_statuses = {
        "completed",
        "inherited_parent_scope",
        "request_error",
        "provider_unavailable",
    }
    incomplete = [
        {
            "provider": run.get("provider"),
            "query": run.get("query"),
            "status": run.get("status"),
        }
        for run in acquisition.get("runs", ())
        if run.get("status") not in terminal_statuses
    ]
    if incomplete:
        violations.append(f"incomplete provider/query units: {incomplete}")

    corpus_path = Path(corpus_manifest["corpus"]["path"])
    corpus_hash = file_sha256(corpus_path)
    if corpus_hash != corpus_manifest["corpus"]["sha256"]:
        violations.append("corpus hash differs from its manifest")
    if graph_manifest.get("corpus_sha256") != corpus_hash:
        violations.append("citation graph was built from a different corpus")
    graph_path = Path(registration["planned_outputs"]["citation_graph"])
    if file_sha256(graph_path) != graph_manifest.get("graph_sha256"):
        violations.append("citation graph hash differs from its manifest")
    if cache.metadata.get("corpus_sha256") != corpus_hash:
        violations.append("SPECTER2 cache was built from a different corpus")
    document_count = corpus_manifest["corpus"]["document_count"]
    if graph_manifest.get("document_count") != document_count:
        violations.append("citation graph document count differs from corpus")
    if cache.embeddings.shape != (document_count, 768):
        violations.append(
            f"unexpected SPECTER2 shape: {tuple(cache.embeddings.shape)}"
        )
    norms = np.linalg.norm(cache.embeddings, axis=1)
    if not np.isfinite(cache.embeddings).all() or np.any(norms <= 0):
        violations.append("SPECTER2 cache contains invalid or zero embeddings")
    if arxiv_audit.get("status") != "pass":
        violations.append("arXiv identity audit did not pass")
    if quality.get("status") != "pass":
        violations.append("corpus quality gate did not pass")

    parent = registration["parent_scope"]
    parent_artifacts = {
        "corpus": (Path(parent["corpus"]), parent["corpus_sha256"]),
        "citation_graph": (
            Path("artifacts/paper_recommendation_scope_v1.citations.tsv"),
            parent["citation_graph_sha256"],
        ),
        "specter2_cache": (
            Path("artifacts/paper_recommendation_scope_v1.specter2.npz"),
            parent["specter2_cache_sha256"],
        ),
    }
    parent_observed = {}
    for name, (path, expected) in parent_artifacts.items():
        observed = file_sha256(path)
        parent_observed[name] = {"path": str(path), "sha256": observed}
        if observed != expected:
            violations.append(f"frozen v1 {name} hash changed")

    report = {
        "format_version": 1,
        "protocol": "scope_completion_manifest",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not violations else "fail",
        "registration": {
            "path": str(args.registration),
            "sha256": file_sha256(args.registration),
            "scope_spec_sha256": scope_hash,
        },
        "acquisition": {
            "path": str(args.acquisition),
            "sha256": file_sha256(args.acquisition),
            "totals": acquisition.get("totals"),
            "run_count": len(acquisition.get("runs", ())),
            "audited_provider_failures": [
                {
                    "provider": run.get("provider"),
                    "query": run.get("query"),
                    "status": run.get("status"),
                }
                for run in acquisition.get("runs", ())
                if run.get("status") in {"request_error", "provider_unavailable"}
            ],
        },
        "artifacts": {
            "corpus": {
                "path": str(corpus_path),
                "sha256": corpus_hash,
                "document_count": document_count,
            },
            "citation_graph": {
                "path": str(graph_path),
                "sha256": graph_manifest["graph_sha256"],
                "edge_count": graph_manifest["edge_count"],
                "resolved_internal_edge_count": graph_manifest[
                    "resolved_internal_edge_count"
                ],
            },
            "specter2_cache": {
                "path": str(args.specter_cache),
                "sha256": file_sha256(args.specter_cache),
                "metadata_sha256": file_sha256(
                    args.specter_cache.with_suffix(".json")
                ),
                "shape": list(cache.embeddings.shape),
                "minimum_embedding_norm": float(norms.min()),
                "maximum_embedding_norm": float(norms.max()),
            },
        },
        "audits": {
            "arxiv_identity": {
                "path": str(args.arxiv_audit),
                "sha256": file_sha256(args.arxiv_audit),
                "status": arxiv_audit["status"],
                "counts": arxiv_audit["counts"],
            },
            "corpus_quality": {
                "path": str(args.quality_report),
                "sha256": file_sha256(args.quality_report),
                "status": quality["status"],
                "violations": quality["violations"],
            },
        },
        "frozen_v1_observed": parent_observed,
        "violations": violations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "status": report["status"],
                "violations": violations,
                "artifacts": report["artifacts"],
            },
            indent=2,
        )
    )
    return 2 if args.fail_on_violation and violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
