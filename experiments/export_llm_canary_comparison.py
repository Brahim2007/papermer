"""Convert the canary artifact into dashboard runs and a concise audit report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(round((len(ordered) - 1) * fraction), len(ordered) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    raw = args.artifact.read_bytes()
    artifact = json.loads(raw)
    rows = artifact["queries"]
    summary = artifact["summary"]
    protocol = artifact["protocol"]
    protocol_label = f"{protocol['name']}:v{protocol['version']}:{protocol['sha256'][:12]}"
    source_sha256 = hashlib.sha256(raw).hexdigest()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline_latencies = [row["baseline"]["latency_ms"] for row in rows]
    treatment_latencies = [
        row["llm_expanded_hybrid_rrf"]["latency_ms"] for row in rows
    ]
    warm_baseline_latencies = baseline_latencies[1:]
    warm_treatment_latencies = treatment_latencies[1:]

    shared = {
        "query_count": len(rows),
        "corpus_sha256": "d491d2eab5986e8480804cee677a87eb8e73d0f7bec8c90c3dc41d355bca50e2",
        "protocol": protocol_label,
        "source_artifact": str(args.artifact),
        "source_artifact_sha256": source_sha256,
        "claim_scope": summary["claim_scope"],
    }
    baseline = {
        **shared,
        "method": "hybrid_specter2_bm25_rrf",
        "aggregate": {
            "semantic_availability_rate": mean(
                float(row["baseline"]["semantic_enabled"]) for row in rows
            ),
            "mean_overlap_at_10_with_treatment": summary["mean_overlap_at_10"],
            "mean_overlap_at_20_with_treatment": summary["mean_overlap_at_20"],
        },
        "system_metrics": {
            "query_latency_ms_mean": summary["retrieval_latency_ms"]["baseline_mean"],
            "cold_start_latency_ms": baseline_latencies[0],
            "warm_query_latency_ms_mean": mean(warm_baseline_latencies),
            "warm_query_latency_ms_p95": percentile(warm_baseline_latencies, 0.95),
        },
        "configuration": {
            "query_source": "seed_title_proxy",
            "relevance_metrics_available": False,
            "specter2_cache_sha256": "5734bb22c8755038b9cab412a5e912639156794bae8ec47982d618fadbdf9e5c",
        },
    }
    treatment = {
        **shared,
        "method": "llm_expanded_hybrid_rrf",
        "aggregate": {
            "canary_completion_rate": summary["completion_rate"],
            "provider_failure_rate": summary["provider_failure_rate"],
            "semantic_availability_rate": mean(
                float(row["llm_expanded_hybrid_rrf"]["semantic_enabled"])
                for row in rows
            ),
            "mean_overlap_at_10_with_baseline": summary["mean_overlap_at_10"],
            "mean_overlap_at_20_with_baseline": summary["mean_overlap_at_20"],
            "mean_new_documents_at_10": summary["mean_new_documents_at_10"],
            "mean_new_documents_at_20": summary["mean_new_documents_at_20"],
        },
        "system_metrics": {
            "query_latency_ms_mean": summary["retrieval_latency_ms"]["llm_expanded_mean"],
            "cold_start_latency_ms": treatment_latencies[0],
            "warm_query_latency_ms_mean": mean(warm_treatment_latencies),
            "warm_query_latency_ms_p95": percentile(warm_treatment_latencies, 0.95),
            "provider_latency_ms_p50": summary["provider_latency_ms"]["p50"],
            "provider_latency_ms_p95": summary["provider_latency_ms"]["p95"],
            "input_tokens": summary["tokens"]["input"],
            "cached_input_tokens": summary["tokens"]["cached_input"],
            "output_tokens": summary["tokens"]["output"],
            "estimated_cost_usd": summary["estimated_cost_usd"],
        },
        "configuration": {
            **artifact["configuration"],
            "query_source": "seed_title_proxy",
            "relevance_metrics_available": False,
        },
    }
    baseline_path = args.output_dir / "llm_canary_v2_baseline.json"
    treatment_path = args.output_dir / "llm_canary_v2_expanded_hybrid_rrf.json"
    write_json(baseline_path, baseline)
    write_json(treatment_path, treatment)

    latency_increase = (
        summary["retrieval_latency_ms"]["llm_expanded_mean"]
        - summary["retrieval_latency_ms"]["baseline_mean"]
    )
    report = f"""# LLM query-expansion canary v2

Protocol checksum: `{protocol['sha256']}`
Source artifact checksum: `{source_sha256}`

| Measure | Baseline Hybrid-RRF | LLM-expanded Hybrid-RRF |
| --- | ---: | ---: |
| Development proxy queries | {len(rows)} | {len(rows)} |
| Semantic channel available | 100% | 100% |
| Mean retrieval latency | {summary['retrieval_latency_ms']['baseline_mean']:.1f} ms | {summary['retrieval_latency_ms']['llm_expanded_mean']:.1f} ms |
| Cold-start latency | {baseline_latencies[0]:.1f} ms | {treatment_latencies[0]:.1f} ms |
| Warm mean latency | {mean(warm_baseline_latencies):.1f} ms | {mean(warm_treatment_latencies):.1f} ms |
| Warm p95 latency | {percentile(warm_baseline_latencies, 0.95):.1f} ms | {percentile(warm_treatment_latencies, 0.95):.1f} ms |
| Mean overlap@10 | — | {summary['mean_overlap_at_10']:.1f}/10 |
| Mean new documents@10 | — | {summary['mean_new_documents_at_10']:.1f} |
| Mean overlap@20 | — | {summary['mean_overlap_at_20']:.1f}/20 |
| Mean new documents@20 | — | {summary['mean_new_documents_at_20']:.1f} |

Provider completion was {summary['completion_rate'] * 100:.1f}% with p50/p95 latency of {summary['provider_latency_ms']['p50']:.1f}/{summary['provider_latency_ms']['p95']:.1f} ms. Total measured usage was {summary['tokens']['input']} input and {summary['tokens']['output']} output tokens, with an estimated Standard-tier cost of ${summary['estimated_cost_usd']:.7f}. Mean end-to-end retrieval latency increased by {latency_increase:.1f} ms when the one-time SPECTER2 cold start is included. Warm-query latency is the relevant deployment diagnostic; the cold start must be handled by production warmup.

## Interpretation boundary

This is an engineering canary, not evidence that LLM expansion improves relevance. All 20 frozen development rows have blank human-query fields, so the public seed title was used as a proxy. No human qrels exist for these 20 rows; therefore nDCG, Recall, MRR, significance tests, and publication claims are intentionally absent. The frozen test assignment was not read or evaluated.
"""
    (args.output_dir / "llm_query_expansion_canary_v2_report.md").write_text(
        report, encoding="utf-8"
    )
    print(baseline_path)
    print(treatment_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
