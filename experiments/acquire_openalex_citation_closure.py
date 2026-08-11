"""Acquire a preregistered, bounded OpenAlex citation closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from experiments.select_openalex_snapshot import write_deterministic_gzip
from scholarly.normalize import normalize_openalex_id
from scholarly.snapshot import file_sha256, iter_jsonl, openalex_scope_rejection


ENDPOINT = "https://api.openalex.org/works"
PROTOCOL = "openalex_shared_reference_closure_acquisition_v1"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_candidates(path: Path, spec: dict) -> list[dict]:
    candidates = [payload for _, payload in iter_jsonl(path)]
    if len(candidates) > int(spec["candidate_pool_cap"]):
        raise ValueError("candidate artifact exceeds the frozen cap")
    seen: set[str] = set()
    previous: tuple[int, str] | None = None
    for expected_rank, candidate in enumerate(candidates, start=1):
        if int(candidate.get("rank") or 0) != expected_rank:
            raise ValueError("candidate ranks must be contiguous and one-based")
        identifier = normalize_openalex_id(str(candidate.get("openalex_id") or ""))
        count = int(candidate.get("distinct_parent_citers") or 0)
        if not identifier or identifier in seen:
            raise ValueError("candidate OpenAlex IDs must be non-empty and unique")
        if count < int(spec["min_distinct_parent_citers"]):
            raise ValueError("candidate is below the frozen citer threshold")
        ordering = (-count, identifier)
        if previous is not None and ordering < previous:
            raise ValueError("candidate artifact violates the frozen ranking")
        candidate["openalex_id"] = identifier
        seen.add(identifier)
        previous = ordering
    return candidates


def _get_json(session: requests.Session, params: dict, *, attempts: int = 6) -> dict:
    for attempt in range(attempts):
        try:
            response = session.get(ENDPOINT, params=params, timeout=90)
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(2**attempt, 30))
            continue
        if response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("OpenAlex returned a non-object response")
            return payload
        if response.status_code not in {429, 500, 502, 503, 504}:
            raise RuntimeError(f"OpenAlex request failed with HTTP {response.status_code}")
        if attempt + 1 == attempts:
            raise RuntimeError(f"OpenAlex retries exhausted at HTTP {response.status_code}")
        retry_after = response.headers.get("Retry-After")
        delay = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        time.sleep(min(delay, 60))
    raise AssertionError("unreachable")


def _signature(*, spec_sha256: str, candidates_sha256: str, batch: list[dict]) -> dict:
    return {
        "protocol": PROTOCOL,
        "spec_sha256": spec_sha256,
        "candidates_sha256": candidates_sha256,
        "candidate_ranks": [int(row["rank"]) for row in batch],
        "openalex_ids": [row["openalex_id"] for row in batch],
    }


def acquire(
    *,
    spec: dict,
    spec_path: Path,
    candidates: list[dict],
    candidates_path: Path,
    api_key: str,
    output: Path,
    reuse_checkpoints_from: Path | None = None,
) -> dict:
    target = int(spec["target_addition_count"])
    batch_size = int(spec["selection"]["batch_size"])
    if not 1 <= batch_size <= 100:
        raise ValueError("OpenAlex batch size must be between 1 and 100")
    if len(candidates) < target:
        raise ValueError("candidate artifact is smaller than the closure target")

    spec_sha256 = file_sha256(spec_path)
    candidates_sha256 = file_sha256(candidates_path)
    checkpoint_root = output.parent / f".{output.name}.batches"
    session = requests.Session()
    accepted: list[dict] = []
    accepted_ids: set[str] = set()
    rejections: Counter[str] = Counter()
    batches: list[dict] = []

    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset : offset + batch_size]
        batch_number = offset // batch_size + 1
        signature = _signature(
            spec_sha256=spec_sha256,
            candidates_sha256=candidates_sha256,
            batch=batch,
        )
        checkpoint = checkpoint_root / f"batch-{batch_number:04d}.json"
        if checkpoint.exists():
            artifact = json.loads(checkpoint.read_text(encoding="utf-8"))
            if artifact.get("signature") != signature:
                raise ValueError(f"checkpoint signature mismatch: {checkpoint}")
        else:
            reusable = (
                reuse_checkpoints_from / checkpoint.name
                if reuse_checkpoints_from is not None
                else None
            )
            if reusable is not None and reusable.exists():
                source = json.loads(reusable.read_text(encoding="utf-8"))
                source_signature = source.get("signature") or {}
                for field in ("protocol", "candidates_sha256", "candidate_ranks", "openalex_ids"):
                    if source_signature.get(field) != signature[field]:
                        raise ValueError(
                            f"reusable checkpoint request mismatch: {reusable}"
                        )
                artifact = {
                    "signature": signature,
                    "meta": source.get("meta") or {},
                    "records": source.get("records") or [],
                    "reused_from": {
                        "path": str(reusable),
                        "sha256": file_sha256(reusable),
                        "spec_sha256": source_signature.get("spec_sha256"),
                    },
                }
            else:
                params = {
                    "api_key": api_key,
                    "filter": "openalex_id:"
                    + "|".join(row["openalex_id"] for row in batch),
                    "per-page": batch_size,
                }
                payload = _get_json(session, params)
                artifact = {
                    "signature": signature,
                    "meta": payload.get("meta") or {},
                    "records": payload.get("results") or [],
                }
            _atomic_json(checkpoint, artifact)
            if "reused_from" not in artifact:
                time.sleep(0.1)

        returned = {
            normalize_openalex_id(str(item.get("id") or "")): item
            for item in artifact.get("records") or []
            if item.get("id")
        }
        accepted_on_batch = 0
        for candidate in batch:
            identifier = candidate["openalex_id"]
            item = returned.get(identifier)
            if item is None:
                rejections["provider_missing"] += 1
                continue
            rejection = openalex_scope_rejection(item, spec)
            if rejection:
                rejections[rejection] += 1
                continue
            if identifier in accepted_ids:
                rejections["duplicate_openalex_id"] += 1
                continue
            item = dict(item)
            item["_papermer_closure"] = {
                "protocol": PROTOCOL,
                "candidate_rank": int(candidate["rank"]),
                "distinct_parent_citers": int(candidate["distinct_parent_citers"]),
                "parent_corpus_sha256": spec["parent_corpus_sha256"],
            }
            accepted.append(item)
            accepted_ids.add(identifier)
            accepted_on_batch += 1
            if len(accepted) == target:
                break
        batches.append(
            {
                "batch": batch_number,
                "candidate_rank_start": int(batch[0]["rank"]),
                "candidate_rank_end": int(batch[-1]["rank"]),
                "requested": len(batch),
                "returned": len(returned),
                "accepted": accepted_on_batch,
                "checkpoint": str(checkpoint),
                "checkpoint_sha256": file_sha256(checkpoint),
                "cost_usd": (artifact.get("meta") or {}).get("cost_usd"),
                "reused_from": artifact.get("reused_from"),
            }
        )
        if len(accepted) == target:
            break

    completed = len(accepted) == target
    output_artifact = None
    if completed:
        accepted.sort(key=lambda item: normalize_openalex_id(str(item["id"])))
        write_deterministic_gzip(output, accepted)
        output_artifact = {"path": str(output), "sha256": file_sha256(output)}
    return {
        "format_version": 1,
        "protocol": PROTOCOL,
        "status": "completed" if completed else "insufficient_candidates",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "spec": {"path": str(spec_path), "sha256": spec_sha256},
        "candidates": {
            "path": str(candidates_path),
            "sha256": candidates_sha256,
            "available": len(candidates),
            "examined": batches[-1]["candidate_rank_end"],
        },
        "target_addition_count": target,
        "document_count": len(accepted),
        "shortfall": max(target - len(accepted), 0),
        "rejections": dict(sorted(rejections.items())),
        "output": output_artifact,
        "checkpoint_root": str(checkpoint_root),
        "batches": batches,
        "source_response_estimated_cost_usd": sum(
            float(row.get("cost_usd") or 0) for row in batches
        ),
        "incremental_cost_usd": sum(
            float(row.get("cost_usd") or 0)
            for row in batches
            if not row.get("reused_from")
        ),
        "reused_batch_count": sum(bool(row.get("reused_from")) for row in batches),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reuse-checkpoints-from", type=Path)
    args = parser.parse_args()
    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if not api_key:
        parser.error("OPENALEX_API_KEY is required")
    if args.output.exists():
        parser.error("output exists; citation-closure artifacts are immutable")
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    if spec.get("protocol") != "openalex_shared_reference_closure_v1":
        parser.error("unexpected citation-closure protocol")
    candidates = load_candidates(args.candidates, spec)
    report = acquire(
        spec=spec,
        spec_path=args.spec,
        candidates=candidates,
        candidates_path=args.candidates,
        api_key=api_key,
        output=args.output,
        reuse_checkpoints_from=args.reuse_checkpoints_from,
    )
    _atomic_json(args.report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "document_count": report["document_count"],
                "examined": report["candidates"]["examined"],
                "rejections": report["rejections"],
                "incremental_cost_usd": report["incremental_cost_usd"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
