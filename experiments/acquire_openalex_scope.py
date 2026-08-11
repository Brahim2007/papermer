"""Acquire a preregistered seeded OpenAlex sample with page-level checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from experiments.select_openalex_snapshot import write_deterministic_gzip
from scholarly.normalize import normalize_openalex_id
from scholarly.snapshot import (
    file_sha256,
    openalex_scope_rejection,
    validate_bulk_scope,
)


ENDPOINT = "https://api.openalex.org/works"
PROTOCOL = "openalex_seeded_stratified_acquisition_v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _subfield_id(item: dict) -> str:
    primary = item.get("primary_topic") or {}
    subfield = primary.get("subfield") or {}
    return str(subfield.get("id") or "").strip().rstrip("/").rsplit("/", 1)[-1]


def canonical_filter(spec: dict, stratum: dict) -> str:
    work_types = "|".join(str(value) for value in stratum["work_types"])
    languages = "|".join(str(value) for value in spec.get("languages") or ())
    filters = [
        f"from_publication_date:{spec['from_date']}",
        f"to_publication_date:{spec['to_date']}",
        f"type:{work_types}",
        "has_abstract:true" if spec.get("require_abstract") else "has_abstract:false",
        f"primary_topic.subfield.id:{stratum['primary_topic_subfield_id']}",
    ]
    if languages:
        filters.append(f"language:{languages}")
    if spec.get("exclude_retracted", True):
        filters.append("is_retracted:false")
    return ",".join(filters)


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
                raise ValueError("OpenAlex returned a non-object JSON response")
            return payload
        if response.status_code not in {429, 500, 502, 503, 504}:
            raise RuntimeError(f"OpenAlex request failed with HTTP {response.status_code}")
        if attempt + 1 == attempts:
            raise RuntimeError(f"OpenAlex retries exhausted at HTTP {response.status_code}")
        retry_after = response.headers.get("Retry-After")
        delay = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
        time.sleep(min(delay, 60))
    raise AssertionError("unreachable")


def _request_params(
    *,
    api_key: str,
    spec: dict,
    stratum: dict,
    page: int,
    page_size: int,
    seed: int | None = None,
) -> dict:
    return {
        "api_key": api_key,
        "filter": canonical_filter(spec, stratum),
        "sample": int(stratum["quota"]),
        "seed": int(stratum["seed"] if seed is None else seed),
        "per_page": page_size,
        "page": page,
    }


def _public_params(params: dict) -> dict:
    return {key: value for key, value in params.items() if key != "api_key"}


def _stratum_rejection(item: dict, spec: dict, stratum: dict) -> str | None:
    rejection = openalex_scope_rejection(item, spec)
    if rejection:
        return rejection
    expected_subfield = str(stratum["primary_topic_subfield_id"])
    if _subfield_id(item) != expected_subfield:
        return "wrong_primary_subfield"
    if str(item.get("type") or "") not in set(stratum["work_types"]):
        return "wrong_work_type"
    return None


def _validate_stratum_record(item: dict, spec: dict, stratum: dict) -> None:
    rejection = _stratum_rejection(item, spec, stratum)
    if rejection:
        raise ValueError(f"provider returned out-of-scope record: {rejection}")


def preflight(spec: dict, *, api_key: str) -> dict:
    session = requests.Session()
    checks = []
    page_size = int(spec["sampling"].get("page_size") or 100)
    for stratum in spec["sampling"]["strata"]:
        params = _request_params(
            api_key=api_key,
            spec=spec,
            stratum=stratum,
            page=1,
            page_size=page_size,
        )
        payload = _get_json(session, params)
        results = payload.get("results") or []
        if not results:
            raise ValueError(f"OpenAlex returned no results for {stratum['name']}")
        for item in results:
            _validate_stratum_record(item, spec, stratum)
        available = int((payload.get("meta") or {}).get("count") or 0)
        quota = int(stratum["quota"])
        if available < quota:
            raise ValueError(
                f"stratum {stratum['name']} has {available} records; requires {quota}"
            )
        checks.append(
            {
                "name": stratum["name"],
                "quota": quota,
                "sample_count": available,
                "first_page_records": len(results),
                "filter": params["filter"],
                "seed": params["seed"],
                "cost_usd": (payload.get("meta") or {}).get("cost_usd"),
            }
        )
    return {"status": "passed", "protocol": PROTOCOL, "strata": checks}


def acquire(spec: dict, spec_raw: bytes, *, api_key: str, output: Path) -> dict:
    page_size = int(spec["sampling"].get("page_size") or 100)
    if not 1 <= page_size <= 100:
        raise ValueError("OpenAlex page_size must be between 1 and 100")
    spec_sha256 = _sha256_bytes(spec_raw)
    checkpoint_root = output.parent / f".{output.name}.pages"
    session = requests.Session()
    page_artifacts: list[dict[str, Any]] = []
    records: list[dict] = []
    seen_ids: set[str] = set()
    duplicate_count = 0
    stratum_reports = []

    for stratum in spec["sampling"]["strata"]:
        quota = int(stratum["quota"])
        page_count = math.ceil(quota / page_size)
        stratum_records = 0
        rejections: Counter[str] = Counter()
        rounds_used = 0
        seeds = [int(stratum["seed"]), *map(int, stratum.get("reserve_seeds") or [])]
        for round_index, seed in enumerate(seeds):
            rounds_used += 1
            for page in range(1, page_count + 1):
                params = _request_params(
                    api_key=api_key,
                    spec=spec,
                    stratum=stratum,
                    page=page,
                    page_size=page_size,
                    seed=seed,
                )
                public_params = _public_params(params)
                signature = {
                    "protocol": PROTOCOL,
                    "spec_sha256": spec_sha256,
                    "stratum": stratum["name"],
                    "round": round_index,
                    "request": public_params,
                }
                page_path = (
                    checkpoint_root
                    / stratum["name"]
                    / f"round-{round_index:02d}"
                    / f"page-{page:03d}.json"
                )
                if page_path.exists():
                    artifact = json.loads(page_path.read_text(encoding="utf-8"))
                    if artifact.get("signature") != signature:
                        raise ValueError(f"checkpoint signature mismatch: {page_path}")
                else:
                    payload = _get_json(session, params)
                    page_records = payload.get("results") or []
                    expected = min(page_size, quota - (page - 1) * page_size)
                    if len(page_records) != expected:
                        raise ValueError(
                            f"{stratum['name']} page {page} returned "
                            f"{len(page_records)} records; expected {expected}"
                        )
                    artifact = {
                        "signature": signature,
                        "meta": payload.get("meta") or {},
                        "records": page_records,
                    }
                    _atomic_json(page_path, artifact)
                raw = page_path.read_bytes()
                page_records = artifact.get("records") or []
                accepted_on_page = 0
                for item in page_records:
                    rejection = _stratum_rejection(item, spec, stratum)
                    if rejection:
                        rejections[rejection] += 1
                        continue
                    identifier = normalize_openalex_id(str(item["id"]))
                    if identifier in seen_ids:
                        duplicate_count += 1
                        continue
                    if stratum_records >= quota:
                        continue
                    seen_ids.add(identifier)
                    records.append(item)
                    stratum_records += 1
                    accepted_on_page += 1
                page_artifacts.append(
                    {
                        "stratum": stratum["name"],
                        "round": round_index,
                        "page": page,
                        "path": str(page_path),
                        "sha256": _sha256_bytes(raw),
                        "records": len(page_records),
                        "accepted": accepted_on_page,
                        "cost_usd": (artifact.get("meta") or {}).get("cost_usd"),
                    }
                )
                if round_index > 0 and stratum_records >= quota:
                    break
            if stratum_records >= quota:
                break
        if stratum_records != quota:
            raise ValueError(
                f"stratum {stratum['name']} produced {stratum_records}; expected {quota}"
            )
        stratum_reports.append(
            {
                "name": stratum["name"],
                "quota": quota,
                "accepted": stratum_records,
                "rounds_used": rounds_used,
                "rejections": dict(sorted(rejections.items())),
            }
        )

    target = int(spec["target_document_count"])
    if len(records) != target:
        raise ValueError(
            f"acquired corpus is not exactly {target} unique records; "
            f"observed {len(records)}"
        )
    records.sort(key=lambda item: normalize_openalex_id(str(item["id"])))
    write_deterministic_gzip(output, records)
    return {
        "protocol": PROTOCOL,
        "status": "completed",
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": ENDPOINT,
        "spec_sha256": spec_sha256,
        "target_document_count": target,
        "document_count": len(records),
        "duplicate_count": duplicate_count,
        "strata": stratum_reports,
        "output": str(output),
        "output_sha256": file_sha256(output),
        "checkpoint_root": str(checkpoint_root),
        "pages": page_artifacts,
        "sampling": spec["sampling"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()

    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if not api_key:
        parser.error("OPENALEX_API_KEY is required")
    spec_raw = args.spec.read_bytes()
    spec = json.loads(spec_raw)
    validate_bulk_scope(spec)
    if spec["sampling"]["method"] != "openalex_seeded_stratified_sample_v1":
        parser.error("scope does not use seeded stratified OpenAlex sampling")

    if args.preflight:
        report = preflight(spec, api_key=api_key)
        report["spec_sha256"] = _sha256_bytes(spec_raw)
    else:
        if args.output.exists():
            parser.error("output exists; acquisition artifacts are immutable")
        report = acquire(spec, spec_raw, api_key=api_key, output=args.output)
    _atomic_json(args.report, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "document_count": report.get("document_count"),
                "report": str(args.report),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
