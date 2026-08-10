from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from scholarly.connectors import (
    ArxivConnector,
    ConnectorRequestError,
    OpenAlexConnector,
    SemanticScholarConnector,
)
from scholarly.ingest import IdentityConflictError, ingest_record, ingest_records


class Command(BaseCommand):
    help = "Expand the canonical corpus from a frozen topical/temporal JSON spec."

    def add_arguments(self, parser):
        parser.add_argument("--spec", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume completed provider/query units from an existing report.",
        )
        parser.add_argument(
            "--inherit-report",
            type=Path,
            help="Reuse audited provider/query units from an invariant parent scope.",
        )

    def handle(self, *args, **options):
        spec_path: Path = options["spec"]
        raw = spec_path.read_bytes()
        spec = json.loads(raw)
        self._validate(spec)
        from_date = date.fromisoformat(spec["from_date"])
        to_date = date.fromisoformat(spec["to_date"])
        per_query_limit = int(spec["per_query_limit"])
        providers = tuple(spec["providers"])
        connectors = {
            "openalex": OpenAlexConnector(email=settings.OPENALEX_EMAIL),
            "semantic_scholar": SemanticScholarConnector(
                api_key=settings.SEMANTIC_SCHOLAR_API_KEY,
                min_interval_seconds=settings.SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS,
            ),
            "arxiv": ArxivConnector(
                min_interval_seconds=settings.ARXIV_MIN_INTERVAL_SECONDS
            ),
        }
        output: Path = options["output"]
        spec_sha256 = hashlib.sha256(raw).hexdigest()
        report = {
            "protocol": "frozen_scoped_corpus_expansion",
            "spec_path": str(spec_path),
            "spec_sha256": spec_sha256,
            "spec": spec,
            "runs": [],
            "totals": {
                "fetched": 0,
                "eligible": 0,
                "created": 0,
                "updated": 0,
                "identity_conflicts": 0,
                "request_errors": 0,
            },
        }
        if options["inherit_report"] and not output.exists():
            report = self._inherit_report(
                report,
                parent_path=options["inherit_report"],
                child_spec=spec,
            )
        completed_units: set[tuple[str, str]] = set()
        if options["resume"] and output.exists():
            previous = json.loads(output.read_text(encoding="utf-8"))
            if previous.get("spec_sha256") != spec_sha256:
                raise CommandError("cannot resume: scope spec hash changed")
            report = previous
            completed_units = {
                (run["provider"], run["query"])
                for run in report["runs"]
                if run.get("status") in {"completed", "inherited_parent_scope"}
            }
        else:
            completed_units = {
                (run["provider"], run["query"])
                for run in report["runs"]
                if run.get("status") in {"completed", "inherited_parent_scope"}
            }
        unavailable: dict[str, str] = {}
        for provider in providers:
            for query in spec["queries"]:
                if (provider, query) in completed_units:
                    continue
                run = {"provider": provider, "query": query}
                if provider in unavailable:
                    run.update(
                        {
                            "status": "provider_unavailable",
                            "reason": unavailable[provider],
                        }
                    )
                    report["runs"].append(run)
                    self._write_report(output, report)
                    continue
                try:
                    records = self._search(
                        connectors[provider],
                        provider,
                        query,
                        from_date=from_date,
                        to_date=to_date,
                        limit=per_query_limit,
                        spec=spec,
                    )
                except ConnectorRequestError as exc:
                    run.update(
                        {
                            "status": "request_error",
                            "reason": str(exc),
                            "http_status": exc.status_code,
                        }
                    )
                    report["totals"]["request_errors"] += 1
                    if exc.status_code in {401, 403}:
                        unavailable[provider] = str(exc)
                    report["runs"].append(run)
                    self._write_report(output, report)
                    continue
                report["totals"]["fetched"] += len(records)
                eligible = [
                    record
                    for record in records
                    if (not spec["require_abstract"] or record.abstract.strip())
                    and (
                        record.publication_date is None
                        or from_date <= record.publication_date <= to_date
                    )
                ]
                report["totals"]["eligible"] += len(eligible)
                created, updated, conflicts = self._ingest(eligible)
                report["totals"]["created"] += created
                report["totals"]["updated"] += updated
                report["totals"]["identity_conflicts"] += conflicts
                run.update(
                    {
                        "status": "completed",
                        "fetched": len(records),
                        "eligible": len(eligible),
                        "created": created,
                        "updated": updated,
                        "identity_conflicts": conflicts,
                    }
                )
                report["runs"].append(run)
                self._write_report(output, report)

        self._write_report(output, report)
        self.stdout.write(self.style.SUCCESS(json.dumps(report["totals"])))

    @staticmethod
    def _ingest(records) -> tuple[int, int, int]:
        try:
            results = ingest_records(records)
            return (
                sum(result.created for result in results),
                sum(not result.created for result in results),
                0,
            )
        except IdentityConflictError:
            created = 0
            updated = 0
            conflicts = 0
            for record in records:
                try:
                    result = ingest_record(record)
                except IdentityConflictError:
                    conflicts += 1
                    continue
                created += int(result.created)
                updated += int(not result.created)
            return created, updated, conflicts

    @staticmethod
    def _inherit_report(report: dict, *, parent_path: Path, child_spec: dict) -> dict:
        raw = parent_path.read_bytes()
        parent = json.loads(raw)
        parent_spec = parent.get("spec") or {}
        invariant_fields = (
            "queries",
            "from_date",
            "to_date",
            "per_query_limit",
            "require_abstract",
        )
        changed = [
            field
            for field in invariant_fields
            if parent_spec.get(field) != child_spec.get(field)
        ]
        if changed:
            raise CommandError(
                f"cannot inherit report: scope invariants changed: {changed}"
            )
        if not set(parent_spec.get("providers", ())) <= set(child_spec["providers"]):
            raise CommandError("cannot inherit report: parent providers are not a subset")
        parent_hash = hashlib.sha256(raw).hexdigest()
        inherited_runs = []
        for run in parent.get("runs", ()):
            inherited_runs.append(
                {
                    **run,
                    "status": "inherited_parent_scope",
                    "inherited_status": run.get("status"),
                    "inherited_from": str(parent_path),
                    "inherited_report_sha256": parent_hash,
                }
            )
        report["runs"] = inherited_runs
        report["totals"] = dict(parent.get("totals") or report["totals"])
        report["inheritance"] = {
            "parent_report": str(parent_path),
            "parent_report_sha256": parent_hash,
            "inherited_run_count": len(inherited_runs),
            "invariant_fields": list(invariant_fields),
        }
        return report

    @staticmethod
    def _write_report(output: Path, report: dict) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(output)

    @staticmethod
    def _validate(spec: dict) -> None:
        required = {
            "format_version",
            "name",
            "queries",
            "providers",
            "from_date",
            "to_date",
            "per_query_limit",
            "require_abstract",
        }
        missing = sorted(required - set(spec))
        if missing:
            raise CommandError(f"scope spec is missing: {missing}")
        if not spec["queries"] or not all(
            str(query).strip() for query in spec["queries"]
        ):
            raise CommandError("scope queries must be non-empty")
        if not set(spec["providers"]) <= {
            "openalex",
            "semantic_scholar",
            "arxiv",
        }:
            raise CommandError("unsupported provider in scope spec")
        from_date = date.fromisoformat(spec["from_date"])
        to_date = date.fromisoformat(spec["to_date"])
        if to_date < from_date:
            raise CommandError("scope to_date precedes from_date")
        if not 1 <= int(spec["per_query_limit"]) <= 100:
            raise CommandError("per_query_limit must be between 1 and 100")

    @staticmethod
    def _search(
        connector,
        provider: str,
        query: str,
        *,
        from_date: date,
        to_date: date,
        limit: int,
        spec: dict,
    ):
        if provider == "openalex":
            return connector.search_scoped(
                query,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                work_types=tuple(spec.get("openalex_work_types", ())),
                languages=tuple(spec.get("languages", ())),
                require_abstract=bool(spec["require_abstract"]),
                sort=spec.get("openalex_sort", "cited_by_count:desc"),
            )
        if provider == "arxiv":
            return connector.search_scoped(
                query,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                categories=tuple(spec.get("arxiv_categories", ())),
                sort=spec.get("arxiv_sort", "relevance"),
            )
        return connector.search_scoped(
            query,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            publication_types=tuple(
                spec.get("semantic_scholar_publication_types", ())
            ),
            fields_of_study=tuple(
                spec.get("semantic_scholar_fields_of_study", ())
            ),
        )
