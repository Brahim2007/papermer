"""Select one development configuration per method family and freeze it."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from experiments.build_temporal_benchmark import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--matrix-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    manifest = json.loads(args.matrix_manifest.read_text(encoding="utf-8"))
    spec_hash = file_sha256(args.spec)
    if manifest.get("stage") != "development" or manifest.get("dry_run"):
        raise ValueError("locking requires a completed development matrix")
    if manifest.get("only"):
        raise ValueError("diagnostic --only matrices cannot be locked")
    if manifest.get("spec_sha256") != spec_hash:
        raise ValueError("development matrix does not match the registered spec")
    if any(run.get("status") != "completed" for run in manifest["runs"]):
        raise ValueError("all registered development runs must complete before locking")
    expected_run_ids = {
        run["run_id"] for run in spec["development_runs"]
    }
    observed_run_ids = {run["run_id"] for run in manifest["runs"]}
    if observed_run_ids != expected_run_ids:
        raise ValueError("development matrix is missing registered runs")

    families = defaultdict(list)
    for run in manifest["runs"]:
        result_path = Path(run["output"])
        if file_sha256(result_path) != run["result_sha256"]:
            raise ValueError(f"result hash changed for {run['run_id']}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        families[run["method"]].append((run, result))

    primary = spec["primary_metric"]
    selected = []
    evidence = {}
    for method, candidates in sorted(families.items()):
        candidates.sort(
            key=lambda item: (
                -float(item[1]["aggregate"][primary]),
                float(item[1]["system_metrics"]["query_latency_ms_p95"]),
                item[0]["run_id"],
            )
        )
        run, result = candidates[0]
        selected.append(run["run_id"])
        evidence[method] = {
            "run_id": run["run_id"],
            "primary_metric": primary,
            "primary_value": result["aggregate"][primary],
            "latency_p95_ms": result["system_metrics"]["query_latency_ms_p95"],
            "result_sha256": run["result_sha256"],
        }

    lock = {
        "protocol": "development_selected_test_configuration_lock",
        "spec_sha256": spec_hash,
        "development_matrix_sha256": file_sha256(args.matrix_manifest),
        "development_queries_sha256": manifest["queries_sha256"],
        "development_qrels_sha256": manifest["qrels_sha256"],
        "selection_rule": spec["selection_rule"],
        "primary_metric": primary,
        "selected_run_ids": selected,
        "selection_evidence": evidence,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    print(f"Locked {len(selected)} method families to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
