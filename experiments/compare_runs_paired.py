"""Paired bootstrap confidence intervals for contract-compatible retrieval runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.summarize_runs import CONTRACT_FIELDS


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(reference: dict, candidate: dict, path: Path) -> None:
    expected = {field: reference.get(field) for field in CONTRACT_FIELDS}
    observed = {field: candidate.get(field) for field in CONTRACT_FIELDS}
    if observed != expected:
        raise ValueError(f"evaluation contract mismatch in {path}")
    reference_ids = [row["query_id"] for row in reference["per_query"]]
    candidate_ids = [row["query_id"] for row in candidate["per_query"]]
    if candidate_ids != reference_ids:
        raise ValueError(f"query order mismatch in {path}")


def paired_bootstrap(
    baseline: np.ndarray,
    candidate: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> dict[str, float]:
    if baseline.shape != candidate.shape or baseline.ndim != 1:
        raise ValueError("paired metric arrays must be one-dimensional and aligned")
    if len(baseline) < 2:
        raise ValueError("paired bootstrap requires at least two queries")
    differences = candidate - baseline
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(differences), size=(samples, len(differences)))
    bootstrap = differences[indices].mean(axis=1)
    observed = float(differences.mean())
    lower, upper = np.quantile(bootstrap, [0.025, 0.975])
    p_value = min(
        1.0,
        2
        * min(
            float(np.mean(bootstrap <= 0)),
            float(np.mean(bootstrap >= 0)),
        ),
    )
    return {
        "baseline_mean": float(baseline.mean()),
        "candidate_mean": float(candidate.mean()),
        "mean_difference": observed,
        "ci95_lower": float(lower),
        "ci95_upper": float(upper),
        "bootstrap_p_value_two_sided": p_value,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument(
        "--include-recommendation-metrics",
        action="store_true",
        help="Also bootstrap per-query diversity, novelty, long-tail, and age.",
    )
    args = parser.parse_args()
    if args.samples < 1_000:
        raise ValueError("use at least 1000 bootstrap samples")

    baseline = _load(args.baseline)
    candidates = [(path, _load(path)) for path in args.candidate]
    for path, candidate in candidates:
        _validate(baseline, candidate, path)
    metrics = sorted(baseline.get("aggregate", {}))
    if args.include_recommendation_metrics:
        metrics.extend(
            metric
            for metric in sorted(baseline.get("recommendation_aggregate", {}))
            if metric in baseline["per_query"][0]
        )
    comparisons = []
    for candidate_index, (path, candidate) in enumerate(candidates):
        for metric_index, metric in enumerate(metrics):
            base_values = np.asarray(
                [row[metric] for row in baseline["per_query"]], dtype=np.float64
            )
            candidate_values = np.asarray(
                [row[metric] for row in candidate["per_query"]], dtype=np.float64
            )
            comparisons.append(
                {
                    "candidate_method": candidate["method"],
                    "candidate_path": str(path),
                    "metric": metric,
                    **paired_bootstrap(
                        base_values,
                        candidate_values,
                        samples=args.samples,
                        seed=args.seed + candidate_index * len(metrics) + metric_index,
                    ),
                }
            )

    result = {
        "protocol": "query_paired_nonparametric_bootstrap",
        "confidence_level": 0.95,
        "samples": args.samples,
        "seed": args.seed,
        "baseline_method": baseline["method"],
        "baseline_path": str(args.baseline),
        "contract": {
            field: baseline.get(field) for field in CONTRACT_FIELDS
        },
        "comparisons": comparisons,
        "multiplicity_note": (
            "Exploratory p-values are unadjusted; pre-register the primary metric "
            "or apply a multiple-comparison correction for confirmatory claims."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {len(comparisons)} paired comparisons to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
