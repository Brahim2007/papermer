from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.models import OfflineEvaluationRun


class Command(BaseCommand):
    help = "Import reproducible offline retrieval result summaries into the evaluation dashboard."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="*", help="Result JSON files or directories.")
        parser.add_argument("--dataset", default="")
        parser.add_argument("--split", default="development")
        parser.add_argument("--frozen", action="store_true")

    def handle(self, *args, **options):
        roots = [Path(value) for value in options["paths"]] or [settings.BASE_DIR / "results"]
        files: list[Path] = []
        for root in roots:
            if root.is_dir():
                files.extend(root.rglob("*.json"))
            elif root.is_file():
                files.append(root)
            else:
                raise CommandError(f"Path does not exist: {root}")

        imported = skipped = 0
        for path in sorted(set(file.resolve() for file in files)):
            raw = path.read_bytes()
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                skipped += 1
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("aggregate"), dict):
                skipped += 1
                continue
            method = str(payload.get("method") or path.stem)
            relative = _relative_path(path)
            checksum = hashlib.sha256(raw).hexdigest()
            run_key = f"{relative}:{checksum[:12]}"
            OfflineEvaluationRun.objects.update_or_create(
                run_key=run_key,
                defaults={
                    "label": path.stem,
                    "method": method,
                    "dataset": options["dataset"] or str(payload.get("corpus_sha256", ""))[:16],
                    "split": options["split"],
                    "protocol": str(payload.get("protocol", "")),
                    "metrics": payload["aggregate"],
                    "system_metrics": payload.get("system_metrics", {}),
                    "configuration": payload.get("configuration", {}),
                    "query_count": int(payload.get("query_count", 0)),
                    "artifact_path": relative,
                    "artifact_sha256": checksum,
                    "is_frozen": options["frozen"],
                },
            )
            imported += 1
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} run(s); skipped {skipped} JSON file(s)."))


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(settings.BASE_DIR))
    except ValueError:
        return str(path)
