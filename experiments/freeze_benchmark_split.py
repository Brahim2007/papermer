"""Freeze development/test query IDs before relevance assessment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def _stable_hash(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def _split_stratum(value: str, stratification: str) -> str:
    parts = dict(
        part.split("=", 1)
        for part in value.split(";")
        if "=" in part
    )
    if stratification == "year_popularity":
        return (
            f"year={parts.get('year', 'unknown')};"
            f"popularity={parts.get('popularity', 'unknown')}"
        )
    return f"popularity={parts.get('popularity', 'unknown')}"


def task_contract_hash(rows: list[dict[str, str]]) -> str:
    payload = [
        {
            "query_id": row["query_id"],
            "task_type": row["task_type"],
            "seed_id": row["seed_id"],
            "stratum": row["stratum"],
        }
        for row in sorted(rows, key=lambda item: item["query_id"])
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def choose_development_ids(
    rows: list[dict[str, str]],
    *,
    dev_count: int,
    seed: int,
    stratification: str = "popularity",
) -> set[str]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[_split_stratum(row["stratum"], stratification)].append(row)
    for group in groups.values():
        group.sort(key=lambda row: _stable_hash(seed, row["query_id"]))
    selected: set[str] = set()
    group_names = sorted(groups, key=lambda name: _stable_hash(seed, name))
    while len(selected) < dev_count:
        progressed = False
        for name in group_names:
            if groups[name] and len(selected) < dev_count:
                selected.add(groups[name].pop(0)["query_id"])
                progressed = True
        if not progressed:
            break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dev-fraction", type=float, default=0.2)
    parser.add_argument("--dev-count", type=int)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument(
        "--stratification",
        choices=("popularity", "year_popularity"),
        default="year_popularity",
    )
    args = parser.parse_args()

    with args.draft.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            {key: str(value).strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]
    if len(rows) < 3:
        raise ValueError("at least three query tasks are required")
    query_ids = [row["query_id"] for row in rows]
    if not all(query_ids) or len(set(query_ids)) != len(query_ids):
        raise ValueError("draft query_ids must be non-empty and unique")
    dev_count = (
        args.dev_count
        if args.dev_count is not None
        else max(1, math.floor(len(rows) * args.dev_fraction))
    )
    if not 1 <= dev_count < len(rows):
        raise ValueError("dev count must leave at least one untouched test query")
    development_ids = choose_development_ids(
        rows,
        dev_count=dev_count,
        seed=args.seed,
        stratification=args.stratification,
    )
    assignments = {
        query_id: ("development" if query_id in development_ids else "test")
        for query_id in sorted(query_ids)
    }
    manifest = {
        "format_version": 1,
        "protocol": "frozen_query_id_split_before_assessment",
        "randomization_seed": args.seed,
        "stratification_key": args.stratification,
        "query_task_contract_sha256": task_contract_hash(rows),
        "query_count": len(rows),
        "development_count": len(development_ids),
        "test_count": len(rows) - len(development_ids),
        "assignments": assignments,
        "policy": {
            "development": "parameter selection and ablations permitted",
            "test": "untouched until all configurations are frozen",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        f"Frozen {manifest['development_count']} development and "
        f"{manifest['test_count']} test query IDs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
