from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from functools import lru_cache

from django.conf import settings
from django.utils.crypto import salted_hmac

from api.models import ExperimentProtocol, RetrievalEvent


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def current_protocol_sha256() -> str:
    protocol = ExperimentProtocol.objects.filter(status__in=["frozen", "active"]).order_by(
        "-version"
    ).first()
    return protocol.spec_sha256 if protocol else ""


def query_digest(query: str) -> str:
    """Return a keyed digest so low-entropy queries cannot be dictionary-reversed."""
    return salted_hmac(
        "papermetrix.retrieval-query.v1",
        query.strip().casefold(),
        secret=settings.RETRIEVAL_TELEMETRY_HMAC_KEY,
        algorithm="sha256",
    ).hexdigest()


def actor_digest(actor_key: str) -> str:
    return salted_hmac(
        "papermetrix.retrieval-actor.v1",
        actor_key,
        secret=settings.RETRIEVAL_TELEMETRY_HMAC_KEY,
        algorithm="sha256",
    ).hexdigest()


def record_retrieval_event(
    *,
    request,
    query: str,
    actor_key: str,
    method: str,
    components: Sequence[str],
    component_latencies_ms: Mapping[str, float],
    total_latency_ms: float,
    results: Sequence[Mapping],
    semantic_enabled: bool,
    degraded_reason: str | None,
    cache_hit: bool,
    experiment_arm: str,
    expansion_status: str = "not_selected",
    expansion_model: str = "",
    expanded_query: str = "",
    expansion_prompt_version: str = "",
    expansion_cache_hit: bool = False,
    expansion_latency_ms: float = 0.0,
    expansion_input_tokens: int = 0,
    expansion_output_tokens: int = 0,
    expansion_cached_input_tokens: int = 0,
    expansion_estimated_cost_usd: float | None = None,
    expansion_provider_response_id: str = "",
    search_filters: Mapping | None = None,
) -> str | None:
    """Persist telemetry without allowing an analytics failure to break search."""
    if not settings.RETRIEVAL_TELEMETRY_ENABLED:
        return None
    try:
        ranks = {
            str(item["id"]): dict(item.get("explanation", {}).get("component_ranks", {}))
            for item in results
        }
        event = RetrievalEvent.objects.create(
            user=request.user if request.user.is_authenticated else None,
            query_digest=query_digest(query),
            actor_digest=actor_digest(actor_key),
            query_text=query if settings.RETRIEVAL_TELEMETRY_STORE_QUERY_TEXT else None,
            query_length=len(query),
            experiment_arm=experiment_arm,
            protocol_sha256=current_protocol_sha256(),
            deployment_version=settings.APP_VERSION,
            method=method,
            components=list(components),
            component_latencies_ms={
                key: round(float(value), 3)
                for key, value in component_latencies_ms.items()
            },
            total_latency_ms=round(float(total_latency_ms), 3),
            result_ids=[str(item["id"]) for item in results],
            result_component_ranks=ranks,
            search_filters=dict(search_filters or {}),
            semantic_enabled=semantic_enabled,
            degraded_reason=degraded_reason or "",
            cache_hit=cache_hit,
            expansion_status=expansion_status,
            expansion_model=expansion_model,
            expansion_query_digest=query_digest(expanded_query) if expanded_query else "",
            expansion_prompt_version=expansion_prompt_version,
            expansion_cache_hit=expansion_cache_hit,
            expansion_latency_ms=round(float(expansion_latency_ms), 3),
            expansion_input_tokens=max(int(expansion_input_tokens), 0),
            expansion_output_tokens=max(int(expansion_output_tokens), 0),
            expansion_cached_input_tokens=max(int(expansion_cached_input_tokens), 0),
            expansion_estimated_cost_usd=expansion_estimated_cost_usd,
            expansion_provider_response_id=expansion_provider_response_id,
        )
        return str(event.request_id)
    except Exception:
        logger.exception("Failed to persist retrieval telemetry")
        return None
