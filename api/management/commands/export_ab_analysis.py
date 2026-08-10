from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from api.models import ExperimentProtocol, RetrievalEvent, RetrievalInteraction


class Command(BaseCommand):
    help = "Export a preregistration-aligned, privacy-safe A/B analysis summary."

    def add_arguments(self, parser):
        parser.add_argument("output")
        parser.add_argument("--protocol-version", type=int, default=1)

    def handle(self, *args, **options):
        protocol = ExperimentProtocol.objects.filter(
            version=options["protocol_version"], status__in=["frozen", "active", "completed"]
        ).first()
        if not protocol:
            raise CommandError("The requested protocol is not frozen.")
        candidates = list(
            RetrievalEvent.objects.filter(protocol_sha256=protocol.spec_sha256)
            .filter(Q(user__isnull=True) | Q(user__is_staff=False))
            .exclude(user__email__endswith=".invalid")
            .exclude(actor_digest="")
            .order_by("created_at", "request_id")
        )
        exclusions = Counter()
        eligible = []
        seen = set()
        for event in candidates:
            if not event.result_ids:
                exclusions["no_results"] += 1
                continue
            key = (event.actor_digest, event.query_digest, event.created_at.date())
            if key in seen:
                exclusions["duplicate_actor_query_day"] += 1
                continue
            seen.add(key)
            eligible.append(event)

        interactions = list(
            RetrievalInteraction.objects.filter(
                retrieval_event_id__in=[event.pk for event in eligible], rank__lte=10
            )
        )
        by_event: dict[object, list[RetrievalInteraction]] = {}
        created_at = {event.pk: event.created_at for event in eligible}
        for item in interactions:
            if item.created_at <= created_at[item.retrieval_event_id] + timedelta(hours=24):
                by_event.setdefault(item.retrieval_event_id, []).append(item)

        arms = {}
        for arm in ("baseline", "llm_expansion"):
            arm_events = [event for event in eligible if event.experiment_arm == arm]
            arm_items = [item for event in arm_events for item in by_event.get(event.pk, [])]
            counts = Counter(item.event_type for item in arm_items)
            judged = [item for item in arm_items if item.event_type == "relevance"]
            success = sum(
                any(
                    item.event_type in {"click", "save"}
                    or (item.event_type == "relevance" and item.relevance == 1)
                    for item in by_event.get(event.pk, [])
                )
                for event in arm_events
            )
            impressions = counts["impression"]
            arms[arm] = {
                "eligible_requests": len(arm_events),
                "successful_search_at_10": _rate(success, len(arm_events)),
                "ctr_at_10": _rate(counts["click"], impressions),
                "save_at_10": _rate(counts["save"], impressions),
                "positive_relevance_rate": _rate(
                    sum(item.relevance == 1 for item in judged), len(judged)
                ),
                "judgment_rate": _rate(len(judged), impressions),
                "provider_failure_rate": _rate(
                    sum(event.expansion_status == "provider_failed" for event in arm_events),
                    len(arm_events),
                ),
                "latency_ms_p50": _percentile(
                    [event.total_latency_ms for event in arm_events], 0.50
                ),
                "latency_ms_p95": _percentile(
                    [event.total_latency_ms for event in arm_events], 0.95
                ),
            }

        output = {
            "protocol": protocol.name,
            "protocol_version": protocol.version,
            "protocol_sha256": protocol.spec_sha256,
            "generated_at": timezone.now().isoformat(),
            "privacy": "aggregate_only_no_raw_queries_or_actor_ids",
            "deployment_versions": sorted({event.deployment_version for event in eligible}),
            "exclusions": dict(exclusions),
            "arms": arms,
        }
        destination = Path(options["output"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"Exported {len(eligible)} eligible requests to {destination}"))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[round((len(ordered) - 1) * proportion)], 3)
