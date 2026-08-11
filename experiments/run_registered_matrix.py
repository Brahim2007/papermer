"""Run or dry-run a hash-locked retrieval experiment matrix."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from benchmark.io import read_benchmark_queries
from experiments.build_temporal_benchmark import file_sha256


def _argument(name: str) -> str:
    return f"--{name}"


def read_qrel_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(
            csv.DictReader(handle, delimiter="\t"), start=2
        ):
            query_id = str(row.get("query_id", "")).strip()
            document_id = str(row.get("document_id", "")).strip()
            if not query_id or not document_id:
                raise ValueError(f"invalid qrels row {line_number}")
            counts[query_id] = counts.get(query_id, 0) + 1
    return counts


def build_command(
    spec: dict,
    run: dict,
    *,
    queries: Path,
    qrels: Path,
    output: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "experiments.evaluate_temporal",
        "--method",
        run["method"],
        "--corpus",
        spec["corpus"],
        "--queries",
        str(queries),
        "--qrels",
        str(qrels),
        "--train-end",
        spec["train_end"],
        "--test-end",
        spec["test_end"],
        "--top-k",
        str(spec["top_k"]),
        "--output",
        str(output),
    ]
    if run["method"] in {
        "specter2",
        "hybrid",
        "hybrid_graph",
        "hybrid_rerank",
        "hybrid_graph_rerank",
    }:
        command.extend(["--specter-cache", spec["specter_cache"]])
    if run["method"] in {"graph", "hybrid_graph", "hybrid_graph_rerank"}:
        command.extend(["--citation-graph", spec["citation_graph"]])
    if spec.get("save_rankings"):
        command.append("--save-rankings")
    for name, value in run.get("params", {}).items():
        if isinstance(value, bool):
            if value:
                command.append(_argument(name))
        else:
            command.extend([_argument(name), str(value)])
    return command


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--stage", choices=("development", "test"), required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lock", type=Path)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run selected registered run_id values; intended for diagnostics.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    spec_hash = file_sha256(args.spec)
    for path_field in (
        "corpus",
        "citation_graph",
        "specter_cache",
        "frozen_query_split",
    ):
        observed = file_sha256(Path(spec[path_field]))
        expected = spec[f"{path_field}_sha256"]
        if observed != expected:
            raise ValueError(f"registered artifact hash changed: {path_field}")
    split = json.loads(
        Path(spec["frozen_query_split"]).read_text(encoding="utf-8")
    )
    expected_query_ids = {
        query_id
        for query_id, partition in split["assignments"].items()
        if partition == args.stage
    }
    observed_query_ids = {
        query.query_id for query in read_benchmark_queries(args.queries)
    }
    if observed_query_ids != expected_query_ids:
        raise ValueError(
            f"{args.stage} query IDs do not match the frozen split"
        )
    required_query_count = spec.get("required_query_count")
    if required_query_count is not None and len(observed_query_ids) != int(
        required_query_count
    ):
        raise ValueError(
            f"expected {required_query_count} {args.stage} queries, "
            f"found {len(observed_query_ids)}"
        )
    qrel_counts = read_qrel_counts(args.qrels)
    qrel_query_ids = set(qrel_counts)
    if qrel_query_ids != expected_query_ids:
        raise ValueError(f"{args.stage} qrels do not match the frozen split")
    minimum_qrels = int(spec.get("minimum_qrels_per_query", 1))
    under_judged = {
        query_id: count
        for query_id, count in qrel_counts.items()
        if count < minimum_qrels
    }
    if under_judged:
        preview = ", ".join(
            f"{query_id}={count}"
            for query_id, count in sorted(under_judged.items())[:5]
        )
        raise ValueError(
            f"qrels require at least {minimum_qrels} judgments per query; "
            f"under-judged: {preview}"
        )
    run_ids = [run["run_id"] for run in spec["development_runs"]]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("registered run_ids must be unique")
    if args.stage == "test":
        if not args.lock:
            raise ValueError("test stage requires --lock from development")
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        if lock.get("spec_sha256") != spec_hash:
            raise ValueError("development lock does not match the registered spec")
        selected = set(lock["selected_run_ids"])
        runs = [run for run in spec["development_runs"] if run["run_id"] in selected]
    else:
        if args.lock:
            raise ValueError("--lock is only valid for the test stage")
        runs = spec["development_runs"]
    if args.only:
        requested = set(args.only)
        unknown = requested - {run["run_id"] for run in runs}
        if unknown:
            raise ValueError(f"unknown or unlocked run_ids: {sorted(unknown)}")
        runs = [run for run in runs if run["run_id"] in requested]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol": "hash_locked_registered_retrieval_matrix",
        "stage": args.stage,
        "dry_run": args.dry_run,
        "only": args.only,
        "spec_path": str(args.spec),
        "spec_sha256": spec_hash,
        "queries_path": str(args.queries),
        "queries_sha256": file_sha256(args.queries),
        "qrels_path": str(args.qrels),
        "qrels_sha256": file_sha256(args.qrels),
        "runs": [],
    }
    manifest_path = args.output_dir / "matrix_manifest.json"
    for run in runs:
        output = args.output_dir / f"{run['run_id']}.json"
        command = build_command(
            spec,
            run,
            queries=args.queries,
            qrels=args.qrels,
            output=output,
        )
        entry = {
            "run_id": run["run_id"],
            "method": run["method"],
            "params": run.get("params", {}),
            "output": str(output),
            "command": command,
            "status": "planned" if args.dry_run else "running",
        }
        manifest["runs"].append(entry)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if args.dry_run:
            continue
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            entry["status"] = "failed"
            entry["returncode"] = completed.returncode
            manifest_path.write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            return completed.returncode
        entry["status"] = "completed"
        entry["result_sha256"] = file_sha256(output)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote registered {args.stage} matrix to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
