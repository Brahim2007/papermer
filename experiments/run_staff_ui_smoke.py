"""Exercise the staff-only LLM expansion channel through its real HTTP API."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urljoin

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PaperMetrics.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from experiments.run_llm_expansion_canary import (  # noqa: E402
    file_sha256,
    load_development_queries,
    percentile,
)
from frontend.query_expansion import PROMPT_VERSION, SYSTEM_PROMPT  # noqa: E402


CSRF_PATTERN = re.compile(
    r'name=["\']csrfmiddlewaretoken["\'][^>]*value=["\']([^"\']+)', re.I
)


def _csrf_token(html: str) -> str:
    match = CSRF_PATTERN.search(html)
    if not match:
        raise RuntimeError("login page did not contain a CSRF token")
    return match.group(1)


def _verify_contract(args: argparse.Namespace, protocol: dict) -> None:
    if not args.execute:
        raise SystemExit("Refusing HTTP/provider calls without --execute")
    if settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT != 0:
        raise SystemExit("Public LLM expansion traffic must remain 0%")
    if not settings.LLM_QUERY_EXPANSION_ENABLED:
        raise SystemExit("LLM query expansion is not enabled")
    if not settings.LLM_QUERY_EXPANSION_STAFF_ONLY:
        raise SystemExit("Staff-only protection must be enabled")
    if settings.LLM_QUERY_EXPANSION_MODEL != protocol["llm"]["model"]:
        raise SystemExit("Configured model differs from the frozen smoke protocol")
    if PROMPT_VERSION != protocol["llm"]["prompt_version"]:
        raise SystemExit("Prompt version differs from the frozen smoke protocol")
    prompt_hash = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    if prompt_hash != protocol["llm"]["prompt_sha256"]:
        raise SystemExit("Prompt checksum differs from the frozen smoke protocol")
    for key, path in (
        ("split_sha256", args.split),
        ("query_draft_sha256", args.queries),
    ):
        if file_sha256(path) != protocol["artifacts"][key]:
            raise SystemExit(f"{key} differs from the frozen smoke protocol")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/")
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "experiments/specs/llm_staff_ui_smoke_v1.json",
    )
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
        "--output",
        type=Path,
        default=ROOT / "results/llm_staff_ui_smoke_v1.json",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    email = os.getenv("PAPERMETRIX_STAFF_EMAIL", "").strip()
    password = os.getenv("PAPERMETRIX_STAFF_PASSWORD", "")
    if not email or not password:
        raise SystemExit("Set PAPERMETRIX_STAFF_EMAIL and PAPERMETRIX_STAFF_PASSWORD")

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    _verify_contract(args, protocol)
    queries = load_development_queries(
        split_path=args.split,
        draft_path=args.queries,
        allow_seed_title_proxy=True,
    )
    request_cap = int(protocol["guardrails"]["maximum_http_requests"])
    if len(queries) != request_cap:
        raise SystemExit("Development query count differs from the frozen HTTP cap")

    base_url = args.base_url.rstrip("/") + "/"
    session = requests.Session()
    login_url = urljoin(base_url, "auth/login/")
    login_page = session.get(login_url, timeout=20)
    login_page.raise_for_status()
    login_response = session.post(
        login_url,
        data={
            "csrfmiddlewaretoken": _csrf_token(login_page.text),
            "email": email,
            "password": password,
            "remember_me": "on",
        },
        headers={"Referer": login_url},
        timeout=20,
    )
    login_response.raise_for_status()
    staff_page = session.get(urljoin(base_url, "search/"), timeout=20)
    staff_page.raise_for_status()
    if "data-expansion-toggle" not in staff_page.text:
        raise SystemExit("Login did not yield the staff-only expansion control")

    rows: list[dict] = []
    consecutive_failures = 0
    stop_after = int(protocol["guardrails"]["stop_after_consecutive_failures"])
    for sequence, item in enumerate(queries, start=1):
        started = time.perf_counter()
        response = session.get(
            urljoin(base_url, "api/search/live/"),
            params={"q": item["query"], "limit": 20, "expansion": "on"},
            timeout=120,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": "non-JSON response"}
        experiment = payload.get("experiment") or {}
        status = str(experiment.get("status") or payload.get("error") or "unknown")
        success = response.status_code == 200 and status in {"expanded", "cached"}
        consecutive_failures = 0 if success else consecutive_failures + 1
        row = {
            "sequence": sequence,
            "query_id": item["query_id"],
            "query": item["query"],
            "query_source": item["query_source"],
            "http_status": response.status_code,
            "request_id": payload.get("request_id", ""),
            "expansion_status": status,
            "cache_hit": bool(experiment.get("cache_hit")),
            "provider_latency_ms": float(experiment.get("latency_ms") or 0),
            "request_latency_ms": float(
                (payload.get("latency_ms") or {}).get("request") or elapsed_ms
            ),
            "input_tokens": int(experiment.get("input_tokens") or 0),
            "cached_input_tokens": int(experiment.get("cached_input_tokens") or 0),
            "output_tokens": int(experiment.get("output_tokens") or 0),
            "estimated_cost_usd": experiment.get("estimated_cost_usd"),
            "semantic_enabled": bool(payload.get("semantic_enabled")),
            "degraded_reason": payload.get("degraded_reason") or "",
            "result_count": len(payload.get("results") or []),
            "error": payload.get("error") or "",
        }
        rows.append(row)
        print(
            f"[{sequence:02d}/{len(queries)}] {item['query_id']} "
            f"HTTP {response.status_code} {status} {elapsed_ms:.0f}ms",
            flush=True,
        )
        if consecutive_failures >= stop_after:
            print("Stopping after the frozen consecutive-failure threshold", flush=True)
            break

    successful = [r for r in rows if r["http_status"] == 200 and r["expansion_status"] == "expanded"]
    costs = [float(r["estimated_cost_usd"]) for r in rows if r["estimated_cost_usd"] is not None]
    provider_latencies = [r["provider_latency_ms"] for r in rows if r["provider_latency_ms"] > 0]
    report = {
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "path": str(args.protocol.resolve()),
            "sha256": file_sha256(args.protocol),
        },
        "environment": {
            "base_url": base_url,
            "staff_email": email,
            "public_traffic_percent": settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT,
            "staff_only": settings.LLM_QUERY_EXPANSION_STAFF_ONLY,
            "model": settings.LLM_QUERY_EXPANSION_MODEL,
        },
        "summary": {
            "attempted": len(rows),
            "successful_expansions": len(successful),
            "failures": len(rows) - len(successful),
            "cache_hits": sum(r["cache_hit"] for r in rows),
            "estimated_cost_usd": round(sum(costs), 9),
            "provider_latency_ms": {
                "p50": round(median(provider_latencies), 3) if provider_latencies else 0,
                "p95": percentile(provider_latencies, 0.95),
            },
            "tokens": {
                "input": sum(r["input_tokens"] for r in rows),
                "cached_input": sum(r["cached_input_tokens"] for r in rows),
                "output": sum(r["output_tokens"] for r in rows),
            },
            "semantic_failures": sum(not r["semantic_enabled"] for r in rows),
            "empty_result_sets": sum(r["result_count"] == 0 for r in rows),
        },
        "requests": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2), flush=True)
    return 0 if len(rows) == request_cap and not report["summary"]["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
