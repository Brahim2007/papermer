"""Run the development-only LLM query-expansion engineering canary.

This script intentionally refuses the frozen test assignment and does not report
relevance metrics because the human-query and qrels artifacts are incomplete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from frontend.query_expansion import (  # noqa: E402
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    expand_query,
)
from frontend.recom import fuse_search_channels, live_search  # noqa: E402


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return round(ordered[position], 3)


def overlap(left: list[str], right: list[str], depth: int) -> int:
    return len(set(left[:depth]) & set(right[:depth]))


def load_development_queries(
    *, split_path: Path, draft_path: Path, allow_seed_title_proxy: bool
) -> list[dict[str, str]]:
    split = json.loads(split_path.read_text(encoding="utf-8"))
    assignments = split.get("assignments") or {}
    development_ids = {
        str(query_id)
        for query_id, assignment in assignments.items()
        if assignment == "development"
    }
    if len(development_ids) != 20:
        raise ValueError(f"expected exactly 20 development IDs, found {len(development_ids)}")

    with draft_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = {
            str(row["query_id"]): row
            for row in csv.DictReader(handle)
            if str(row.get("query_id", "")) in development_ids
        }
    if set(rows) != development_ids:
        missing = sorted(development_ids - set(rows))
        raise ValueError(f"development rows are missing: {missing}")

    queries = []
    for query_id in sorted(development_ids):
        row = rows[query_id]
        human_query = str(row.get("query", "")).strip()
        if human_query:
            text = human_query
            source = "human_query"
        elif allow_seed_title_proxy:
            text = str(row.get("seed_title", "")).strip()
            source = "seed_title_proxy"
        else:
            raise ValueError(
                f"{query_id} has no human query; pass --allow-seed-title-proxy "
                "for the engineering canary only"
            )
        if not text:
            raise ValueError(f"{query_id} has no usable query text")
        if assignments.get(query_id) != "development":
            raise ValueError(f"refusing non-development query {query_id}")
        queries.append(
            {
                "query_id": query_id,
                "query": text,
                "query_source": source,
                "seed_id": str(row.get("seed_id", "")).strip(),
            }
        )
    return queries


def filtered_ids(response, seed_id: str, depth: int = 20) -> list[str]:
    return [
        item.document_id
        for item in response.results
        if item.document_id != seed_id
    ][:depth]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split",
        type=Path,
        default=ROOT / "artifacts/benchmark_query_split_scope_v1_frozen.json",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=ROOT / "artifacts/benchmark_query_draft_scope_v1_100.csv",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "experiments/specs/llm_query_expansion_canary_v2.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results/llm_query_expansion_canary_v2.json",
    )
    parser.add_argument("--allow-seed-title-proxy", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        raise SystemExit("Refusing provider calls without the explicit --execute flag")
    if not settings.LLM_QUERY_EXPANSION_ENABLED:
        raise SystemExit("Set LLM_QUERY_EXPANSION_ENABLED=true for this process only")
    if settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT != 0:
        raise SystemExit("Live expansion traffic must remain 0 during the canary")
    if settings.LLM_QUERY_EXPANSION_MODEL != "gpt-5.6-luna":
        raise SystemExit("Protocol v2 requires model gpt-5.6-luna")
    if PROMPT_VERSION != "scholarly-query-expansion-v1":
        raise SystemExit("Protocol v2 requires prompt scholarly-query-expansion-v1")

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    expected_prompt_hash = protocol["llm"]["prompt_sha256"]
    observed_prompt_hash = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    if observed_prompt_hash != expected_prompt_hash:
        raise SystemExit("Prompt checksum differs from frozen protocol v2")
    for name, path in (("split_sha256", args.split), ("query_draft_sha256", args.queries)):
        if file_sha256(path) != protocol["artifacts"][name]:
            raise SystemExit(f"{name} differs from frozen protocol v2")

    queries = load_development_queries(
        split_path=args.split,
        draft_path=args.queries,
        allow_seed_title_proxy=args.allow_seed_title_proxy,
    )
    if len(queries) > int(protocol["guardrails"]["maximum_provider_calls"]):
        raise SystemExit("Canary exceeds the frozen provider-call cap")

    rows = []
    for index, item in enumerate(queries, start=1):
        expansion = expand_query(
            query=item["query"],
            client_key=f"offline-canary-v2:{item['query_id']}",
            mode="on",
            is_staff=True,
        )
        baseline = live_search(item["query"], top_k=50)
        treatment = baseline
        if expansion.status == "expanded":
            expanded = live_search(expansion.query, top_k=50)
            treatment = fuse_search_channels(
                baseline,
                expanded,
                top_k=50,
                expansion_latency_ms=expansion.latency_ms,
            )
        baseline_ids = filtered_ids(baseline, item["seed_id"])
        treatment_ids = filtered_ids(treatment, item["seed_id"])
        rows.append(
            {
                **item,
                "expansion": {
                    "status": expansion.status,
                    "query": expansion.query,
                    "model": expansion.model,
                    "prompt_version": expansion.prompt_version,
                    "cache_hit": expansion.cache_hit,
                    "latency_ms": round(expansion.latency_ms, 3),
                    "input_tokens": expansion.input_tokens,
                    "output_tokens": expansion.output_tokens,
                    "cached_input_tokens": expansion.cached_input_tokens,
                    "estimated_cost_usd": expansion.estimated_cost_usd,
                    "provider_response_id": expansion.provider_response_id,
                },
                "baseline": {
                    "method": baseline.method,
                    "semantic_enabled": baseline.semantic_enabled,
                    "degraded_reason": baseline.degraded_reason,
                    "latency_ms": round(baseline.total_latency_ms, 3),
                    "result_ids": baseline_ids,
                },
                "llm_expanded_hybrid_rrf": {
                    "method": treatment.method,
                    "semantic_enabled": treatment.semantic_enabled,
                    "degraded_reason": treatment.degraded_reason,
                    "latency_ms": round(treatment.total_latency_ms, 3),
                    "result_ids": treatment_ids,
                },
                "paired_diagnostics": {
                    "overlap_at_10": overlap(baseline_ids, treatment_ids, 10),
                    "overlap_at_20": overlap(baseline_ids, treatment_ids, 20),
                    "new_documents_at_10": 10 - overlap(baseline_ids, treatment_ids, 10),
                    "new_documents_at_20": 20 - overlap(baseline_ids, treatment_ids, 20),
                },
                "sequence": index,
            }
        )
        print(
            f"[{index:02d}/20] {item['query_id']} {expansion.status} "
            f"{expansion.latency_ms:.0f}ms"
        )

    successful = [row for row in rows if row["expansion"]["status"] == "expanded"]
    provider_latencies = [row["expansion"]["latency_ms"] for row in rows]
    baseline_latencies = [row["baseline"]["latency_ms"] for row in rows]
    treatment_latencies = [
        row["llm_expanded_hybrid_rrf"]["latency_ms"] for row in rows
    ]
    priced_costs = [
        row["expansion"]["estimated_cost_usd"]
        for row in rows
        if row["expansion"]["estimated_cost_usd"] is not None
    ]
    summary = {
        "claim_scope": "engineering canary only; no relevance/effectiveness claim",
        "query_count": len(rows),
        "successful_expansions": len(successful),
        "completion_rate": round(len(successful) / len(rows), 4),
        "provider_failure_rate": round((len(rows) - len(successful)) / len(rows), 4),
        "provider_latency_ms": {
            "mean": round(mean(provider_latencies), 3),
            "p50": round(median(provider_latencies), 3),
            "p95": percentile(provider_latencies, 0.95),
        },
        "retrieval_latency_ms": {
            "baseline_mean": round(mean(baseline_latencies), 3),
            "llm_expanded_mean": round(mean(treatment_latencies), 3),
        },
        "tokens": {
            "input": sum(row["expansion"]["input_tokens"] for row in rows),
            "cached_input": sum(
                row["expansion"]["cached_input_tokens"] for row in rows
            ),
            "output": sum(row["expansion"]["output_tokens"] for row in rows),
        },
        "estimated_cost_usd": round(sum(priced_costs), 9) if priced_costs else None,
        "mean_overlap_at_10": round(
            mean(row["paired_diagnostics"]["overlap_at_10"] for row in rows), 3
        ),
        "mean_overlap_at_20": round(
            mean(row["paired_diagnostics"]["overlap_at_20"] for row in rows), 3
        ),
        "mean_new_documents_at_10": round(
            mean(row["paired_diagnostics"]["new_documents_at_10"] for row in rows),
            3,
        ),
        "mean_new_documents_at_20": round(
            mean(row["paired_diagnostics"]["new_documents_at_20"] for row in rows),
            3,
        ),
    }
    artifact = {
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "name": protocol["protocol"],
            "version": protocol["version"],
            "sha256": file_sha256(args.protocol),
        },
        "configuration": {
            "model": settings.LLM_QUERY_EXPANSION_MODEL,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": observed_prompt_hash,
            "pricing_usd_per_million": {
                "input": settings.LLM_QUERY_EXPANSION_INPUT_USD_PER_MILLION,
                "cached_input": settings.LLM_QUERY_EXPANSION_CACHED_INPUT_USD_PER_MILLION,
                "output": settings.LLM_QUERY_EXPANSION_OUTPUT_USD_PER_MILLION,
            },
            "live_traffic_percent": settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT,
        },
        "inputs": {
            "split": str(args.split),
            "split_sha256": file_sha256(args.split),
            "queries": str(args.queries),
            "queries_sha256": file_sha256(args.queries),
        },
        "summary": summary,
        "queries": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    manifest = {
        "artifact": str(args.output),
        "artifact_sha256": file_sha256(args.output),
        "protocol_sha256": file_sha256(args.protocol),
        "query_count": len(rows),
        "test_queries_accessed": 0,
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
