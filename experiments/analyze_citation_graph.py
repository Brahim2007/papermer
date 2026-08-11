"""Measure structural coverage of a corpus-aligned citation graph."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


class DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.size: dict[str, int] = {}

    def find(self, value: str) -> str:
        if value not in self.parent:
            self.parent[value] = value
            self.size[value] = 1
            return value
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            value, self.parent[value] = self.parent[value], root
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]


def analyze_graph(graph_path: Path, *, document_count: int) -> dict:
    edge_count = 0
    internal_edge_count = 0
    outgoing_documents: set[str] = set()
    internal_outgoing: set[str] = set()
    internal_incoming: set[str] = set()
    first_citer: dict[str, str] = {}
    shared_references: set[str] = set()
    coupling_documents: set[str] = set()
    components = DisjointSet()

    with graph_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            citing = str(row["citing_document_id"])
            reference = str(row["cited_reference_key"])
            cited = str(row.get("cited_document_id") or "")
            edge_count += 1
            outgoing_documents.add(citing)
            previous = first_citer.setdefault(reference, citing)
            if previous != citing:
                shared_references.add(reference)
                coupling_documents.update((previous, citing))
            if cited and cited != citing:
                internal_edge_count += 1
                internal_outgoing.add(citing)
                internal_incoming.add(cited)
                components.union(citing, cited)

    component_sizes: dict[str, int] = {}
    for document_id in components.parent:
        root = components.find(document_id)
        component_sizes[root] = component_sizes.get(root, 0) + 1
    incident = internal_outgoing | internal_incoming
    largest_component = max(component_sizes.values(), default=0)
    return {
        "document_count": document_count,
        "edge_count": edge_count,
        "documents_with_outgoing_references": len(outgoing_documents),
        "outgoing_document_coverage": len(outgoing_documents) / document_count,
        "resolved_internal_edge_count": internal_edge_count,
        "internal_edge_rate": internal_edge_count / edge_count if edge_count else 0.0,
        "internal_outgoing_document_count": len(internal_outgoing),
        "internal_incoming_document_count": len(internal_incoming),
        "internal_incident_document_count": len(incident),
        "internal_incident_document_coverage": len(incident) / document_count,
        "mean_internal_incident_degree": 2 * internal_edge_count / document_count,
        "weak_component_count_with_edges": len(component_sizes),
        "largest_weak_component_size": largest_component,
        "largest_weak_component_coverage": largest_component / document_count,
        "shared_reference_count": len(shared_references),
        "bibliographic_coupling_document_count": len(coupling_documents),
        "bibliographic_coupling_document_coverage": len(coupling_documents)
        / document_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    corpus_manifest = json.loads(args.corpus_manifest.read_text(encoding="utf-8"))
    graph_manifest_path = args.graph.with_suffix(".manifest.json")
    graph_manifest = json.loads(graph_manifest_path.read_text(encoding="utf-8"))
    corpus_sha256 = corpus_manifest["corpus"]["sha256"]
    if graph_manifest.get("corpus_sha256") != corpus_sha256:
        raise ValueError("citation graph was built from a different corpus")
    if file_sha256(args.graph) != graph_manifest.get("graph_sha256"):
        raise ValueError("citation graph checksum differs from its manifest")
    metrics = analyze_graph(
        args.graph, document_count=int(corpus_manifest["corpus"]["document_count"])
    )
    report = {
        "format_version": 1,
        "protocol": "citation_graph_structural_audit_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "manifest": str(args.corpus_manifest),
            "sha256": corpus_sha256,
        },
        "graph": {
            "path": str(args.graph),
            "sha256": graph_manifest["graph_sha256"],
            "manifest_sha256": file_sha256(graph_manifest_path),
        },
        "metrics": metrics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
