from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.models import ExperimentProtocol


class Command(BaseCommand):
    help = "Checksum-lock an A/B protocol while experimental traffic is still zero."

    def add_arguments(self, parser):
        parser.add_argument("spec")

    def handle(self, *args, **options):
        if settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT != 0:
            raise CommandError("Set LLM_QUERY_EXPANSION_TRAFFIC_PERCENT=0 before freezing.")
        path = Path(options["spec"]).resolve()
        if not path.is_file():
            raise CommandError(f"Protocol does not exist: {path}")
        raw = path.read_bytes()
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError("Protocol must be valid UTF-8 JSON.") from exc
        _validate(payload)
        checksum = hashlib.sha256(raw).hexdigest()
        name = payload["protocol"]
        version = int(payload["version"])
        existing = ExperimentProtocol.objects.filter(name=name, version=version).first()
        if existing and existing.spec_sha256 != checksum:
            raise CommandError("This protocol version is already frozen with another checksum.")
        protocol, created = ExperimentProtocol.objects.get_or_create(
            name=name,
            version=version,
            defaults={
                "spec_sha256": checksum,
                "payload": payload,
                "status": "frozen",
            },
        )
        verb = "Frozen" if created else "Verified"
        self.stdout.write(self.style.SUCCESS(f"{verb} {name} v{version}: {protocol.spec_sha256}"))


def _validate(payload: dict) -> None:
    required = {
        "protocol",
        "version",
        "arms",
        "primary_outcome",
        "sample_size",
        "analysis_plan",
        "guardrails",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise CommandError(f"Protocol is missing: {', '.join(missing)}")
    allocations = [float(arm["allocation"]) for arm in payload["arms"].values()]
    if len(allocations) != 2 or abs(sum(allocations) - 1.0) > 1e-9:
        raise CommandError("Exactly two arms whose allocations sum to 1 are required.")
    if int(payload["sample_size"].get("analyzable_requests_per_arm", 0)) < 1:
        raise CommandError("A fixed positive sample size per arm is required.")
    if payload["guardrails"].get("traffic_before_freeze") != 0:
        raise CommandError("traffic_before_freeze must be zero.")
