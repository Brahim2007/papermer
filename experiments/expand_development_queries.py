"""Expand only checksum-locked human development queries for pool construction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from benchmark.io import read_benchmark_queries  # noqa: E402
from experiments.build_temporal_benchmark import file_sha256  # noqa: E402
from frontend.query_expansion import PROMPT_VERSION, SYSTEM_PROMPT, expand_query  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing provider calls without --execute")
    if not settings.LLM_QUERY_EXPANSION_ENABLED:
        raise SystemExit("Set LLM_QUERY_EXPANSION_ENABLED=true for this process only")
    if settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT != 0:
        raise SystemExit("Live traffic must remain zero")

    split = json.loads(args.split.read_text(encoding="utf-8"))
    development_ids = {
        query_id
        for query_id, partition in split["assignments"].items()
        if partition == "development"
    }
    queries = read_benchmark_queries(args.queries)
    query_ids = {query.query_id for query in queries}
    if query_ids != development_ids or len(queries) != 20:
        raise SystemExit("Input must contain all and only the 20 development queries")

    rows = []
    for index, query in enumerate(queries, start=1):
        expansion = expand_query(
            query=query.text,
            client_key=f"human-development-expansion:{query.query_id}",
            mode="on",
            is_staff=True,
        )
        rows.append(
            {
                "query_id": query.query_id,
                "query_sha256": hashlib.sha256(query.text.encode()).hexdigest(),
                "expanded_query": expansion.query,
                "status": expansion.status,
                "model": expansion.model,
                "prompt_version": expansion.prompt_version,
                "latency_ms": round(expansion.latency_ms, 3),
                "cache_hit": expansion.cache_hit,
                "input_tokens": expansion.input_tokens,
                "cached_input_tokens": expansion.cached_input_tokens,
                "output_tokens": expansion.output_tokens,
                "estimated_cost_usd": expansion.estimated_cost_usd,
                "provider_response_id": expansion.provider_response_id,
            }
        )
        print(f"[{index:02d}/20] {query.query_id} {expansion.status}")
    failed = [row["query_id"] for row in rows if row["status"] != "expanded"]
    if failed:
        raise SystemExit(f"Expansion failed for {failed}; no artifact was frozen")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "format_version": 1,
        "protocol": "human_development_query_expansion",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_count": len(rows),
        "test_queries_accessed": 0,
        "queries_sha256": file_sha256(args.queries),
        "split_sha256": file_sha256(args.split),
        "model": settings.LLM_QUERY_EXPANSION_MODEL,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "output_sha256": file_sha256(args.output),
        "tokens": {
            "input": sum(row["input_tokens"] for row in rows),
            "cached_input": sum(row["cached_input_tokens"] for row in rows),
            "output": sum(row["output_tokens"] for row in rows),
        },
        "estimated_cost_usd": round(
            sum(row["estimated_cost_usd"] or 0 for row in rows), 9
        ),
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Frozen {len(rows)} expansions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
