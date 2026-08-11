from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from scholarly.connectors import OpenAlexConnector
from scholarly.ingest import IdentityConflictError, ingest_record, ingest_records
from scholarly.snapshot import (
    file_sha256,
    iter_jsonl,
    openalex_scope_rejection,
    snapshot_target_count,
    validate_bulk_scope,
)


class Command(BaseCommand):
    help = "Import a preregistered OpenAlex JSONL snapshot with resumable batches."

    def add_arguments(self, parser):
        parser.add_argument("--input", type=Path, action="append", required=True)
        parser.add_argument("--spec", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--batch-size", type=int, default=250)
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        inputs = [path.resolve() for path in options["input"]]
        missing = [str(path) for path in inputs if not path.is_file()]
        if missing:
            raise CommandError(f"snapshot input not found: {missing}")
        if not 1 <= options["batch_size"] <= 5000:
            raise CommandError("--batch-size must be between 1 and 5000")

        spec_path: Path = options["spec"]
        try:
            spec_raw = spec_path.read_bytes()
            spec = json.loads(spec_raw)
            validate_bulk_scope(spec)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc

        signature = {
            "spec_sha256": hashlib.sha256(spec_raw).hexdigest(),
            "inputs": {str(path): file_sha256(path) for path in inputs},
        }
        output: Path = options["output"]
        report = self._initial_report(spec_path, spec, signature, options["dry_run"])
        if options["resume"] and output.exists():
            report = json.loads(output.read_text(encoding="utf-8"))
            if report.get("signature") != signature:
                raise CommandError("cannot resume: spec or snapshot checksum changed")
            if bool(report.get("dry_run")) != bool(options["dry_run"]):
                raise CommandError("cannot resume between dry-run and write mode")
        elif output.exists():
            raise CommandError("output exists; use --resume or choose another path")

        connector = OpenAlexConnector()
        for path in inputs:
            state = report["files"].setdefault(
                str(path),
                {"processed_lines": 0, "eligible": 0, "status": "pending"},
            )
            if state.get("status") == "completed":
                continue
            batch = []
            rejection_counts = Counter(state.get("rejections") or {})
            for line_number, payload in iter_jsonl(
                path, skip_lines=int(state["processed_lines"])
            ):
                state["processed_lines"] = line_number
                rejection = openalex_scope_rejection(payload, spec)
                if rejection:
                    rejection_counts[rejection] += 1
                else:
                    try:
                        batch.append(connector._record(payload))
                    except (KeyError, TypeError, ValueError):
                        rejection_counts["invalid_record"] += 1
                if len(batch) >= options["batch_size"]:
                    self._flush(batch, report, state, dry_run=options["dry_run"])
                    batch.clear()
                    state["rejections"] = dict(sorted(rejection_counts.items()))
                    self._write_report(output, report)
            if batch:
                self._flush(batch, report, state, dry_run=options["dry_run"])
            state["rejections"] = dict(sorted(rejection_counts.items()))
            state["status"] = "completed"
            self._write_report(output, report)

        report["status"] = "completed"
        target = snapshot_target_count(spec)
        report["target_check"] = {
            "target_document_count": target,
            "eligible_records": report["totals"]["eligible"],
            "met": report["totals"]["eligible"] == target,
        }
        self._write_report(output, report)
        self.stdout.write(self.style.SUCCESS(json.dumps(report["totals"])))
        if not report["target_check"]["met"]:
            raise CommandError(
                f"eligible corpus must contain exactly {target} records; "
                f"observed {report['totals']['eligible']}"
            )

    @staticmethod
    def _initial_report(spec_path, spec, signature, dry_run):
        return {
            "protocol": "preregistered_bulk_snapshot_import_v1",
            "status": "running",
            "dry_run": bool(dry_run),
            "spec_path": str(spec_path),
            "spec": spec,
            "signature": signature,
            "files": {},
            "totals": {
                "eligible": 0,
                "created": 0,
                "updated": 0,
                "identity_conflicts": 0,
            },
        }

    @staticmethod
    def _flush(batch, report, state, *, dry_run):
        state["eligible"] += len(batch)
        report["totals"]["eligible"] += len(batch)
        if dry_run:
            return
        try:
            results = ingest_records(batch)
            created = sum(result.created for result in results)
            updated = len(results) - created
            conflicts = 0
        except IdentityConflictError:
            created = updated = conflicts = 0
            for record in batch:
                try:
                    result = ingest_record(record)
                except IdentityConflictError:
                    conflicts += 1
                    continue
                created += int(result.created)
                updated += int(not result.created)
        report["totals"]["created"] += created
        report["totals"]["updated"] += updated
        report["totals"]["identity_conflicts"] += conflicts

    @staticmethod
    def _write_report(output: Path, report: dict) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(output)
