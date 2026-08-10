from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
import logging
from statistics import median

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import translation
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import DetailView
from api.models import (
    Article,
    Authors,
    ExperimentProtocol,
    Library,
    OfflineEvaluationRun,
    RetrievalEvent,
    RetrievalInteraction,
    Review,
)

from .query_expansion import PROMPT_VERSION, expand_query, should_expand
from .interactions import record_impressions, record_interaction
from .recom import (
    fuse_search_channels,
    get_similar_items,
    live_search,
    matched_query_terms,
)
from .retrieval_telemetry import record_retrieval_event
from .search_filters import (
    apply_search_filters,
    canonical_filter_key,
    parse_search_filters,
)
from .utils import get_article_from_authors, get_mendeley_access_token


logger = logging.getLogger(__name__)


def _article_payload(article: Article) -> dict:
    return {
        "id": str(article.pk),
        "title": article.title,
        "summary": article.abstract[:350],
        "year": article.year,
        "source": article.source,
        "score": article.score,
    }


def _ordered_articles(article_ids: list[str]) -> list[Article]:
    by_id = Article.objects.in_bulk(article_ids)
    return [by_id[article_id] for article_id in article_ids if article_id in by_id]


def home(request):
    request.session.setdefault("lan", "English")
    latest_articles = Article.objects.prefetch_related("authors").order_by(
        F("publication_date").desc(nulls_last=True),
        F("year").desc(nulls_last=True),
        "-add_on",
    )[:6]
    return render(
        request,
        "frontend/index.html",
        {"latest_articles": latest_articles},
    )


@require_GET
def api_get_articles(request):
    articles = Article.objects.order_by("-add_on")[:20]
    return JsonResponse([_article_payload(article) for article in articles], safe=False)


@require_GET
def api_live_search(request):
    request_started = time.perf_counter()
    query = (request.GET.get("q") or "").strip()
    if len(query) < 3:
        return JsonResponse({"error": "query must contain at least 3 characters"}, status=400)
    if len(query) > 500:
        return JsonResponse({"error": "query must not exceed 500 characters"}, status=400)
    try:
        limit = min(max(int(request.GET.get("limit", "12")), 1), 20)
    except ValueError:
        return JsonResponse({"error": "limit must be an integer"}, status=400)
    try:
        search_filters = parse_search_filters(request.GET)
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    expansion_mode = (request.GET.get("expansion") or "auto").strip().lower()
    if expansion_mode not in {"auto", "off", "on"}:
        return JsonResponse({"error": "expansion must be auto, off, or on"}, status=400)
    if expansion_mode == "on" and not request.user.is_staff:
        return JsonResponse({"error": "forcing the experimental arm requires staff access"}, status=403)

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    client = (
        forwarded.split(",", 1)[0].strip()
        if settings.TRUST_PROXY_HEADERS and forwarded
        else request.META.get("REMOTE_ADDR", "unknown")
    )
    client_digest = hashlib.sha256(client.encode("utf-8")).hexdigest()[:20]
    rate_key = f"live-search-rate:{client_digest}"
    request_count = int(cache.get(rate_key, 0))
    if request_count >= 30:
        response = JsonResponse({"error": "live search rate limit exceeded"}, status=429)
        response["Retry-After"] = "60"
        return response
    cache.set(rate_key, request_count + 1, 60)

    client_key = str(request.user.pk) if request.user.is_authenticated else client_digest
    expansion_selected = should_expand(
        query=query,
        client_key=client_key,
        mode=expansion_mode,
        is_staff=request.user.is_staff,
    )
    experiment_arm = "llm_expansion" if expansion_selected else "baseline"
    digest = hashlib.sha256(
        f"{query.casefold()}:{limit}:{experiment_arm}:"
        f"{canonical_filter_key(search_filters)}:"
        f"{settings.LLM_QUERY_EXPANSION_MODEL}:{PROMPT_VERSION}".encode("utf-8")
    ).hexdigest()
    cache_key = f"live-search:v3:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        payload = dict(cached)
        payload["cache_hit"] = True
        experiment = dict(payload.get("experiment", {}))
        if experiment.get("arm") == "llm_expansion":
            experiment.update(
                {
                    "cache_hit": True,
                    "latency_ms": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_input_tokens": 0,
                    "estimated_cost_usd": None,
                    "provider_response_id": "",
                }
            )
        payload["experiment"] = experiment
        request_ms = (time.perf_counter() - request_started) * 1000
        payload["latency_ms"] = {
            **payload.get("latency_ms", {}),
            "request": round(request_ms, 3),
        }
        event_id = record_retrieval_event(
            request=request,
            query=query,
            actor_key=client_key,
            method=payload["method"],
            components=payload["components"],
            component_latencies_ms=payload["latency_ms"].get("components", {}),
            total_latency_ms=request_ms,
            results=payload["results"],
            semantic_enabled=payload["semantic_enabled"],
            degraded_reason=payload.get("degraded_reason"),
            cache_hit=True,
            experiment_arm=payload["experiment"]["arm"],
            expansion_status=payload["experiment"]["status"],
            expansion_model=payload["experiment"].get("model", ""),
            expansion_prompt_version=payload["experiment"].get("prompt_version", ""),
            expansion_cache_hit=payload["experiment"].get("cache_hit", False),
            expansion_latency_ms=payload["experiment"].get("latency_ms", 0.0),
            expansion_input_tokens=payload["experiment"].get("input_tokens", 0),
            expansion_output_tokens=payload["experiment"].get("output_tokens", 0),
            expansion_cached_input_tokens=payload["experiment"].get(
                "cached_input_tokens", 0
            ),
            expansion_estimated_cost_usd=payload["experiment"].get(
                "estimated_cost_usd"
            ),
            expansion_provider_response_id=payload["experiment"].get(
                "provider_response_id", ""
            ),
            search_filters=search_filters,
        )
        payload["request_id"] = event_id
        return JsonResponse(payload)

    expansion = expand_query(
        query=query,
        client_key=client_key,
        mode=expansion_mode,
        is_staff=request.user.is_staff,
    )
    candidate_depth = 50 if expansion.status == "expanded" or search_filters else limit
    baseline = live_search(query, top_k=candidate_depth)
    response = baseline
    if expansion.status == "expanded":
        expanded = live_search(expansion.query, top_k=50)
        response = fuse_search_channels(
            baseline,
            expanded,
            top_k=candidate_depth,
            expansion_latency_ms=expansion.latency_ms,
        )
    ids = [result.document_id for result in response.results]
    eligible_articles = apply_search_filters(
        Article.objects.filter(pk__in=ids), search_filters
    ).prefetch_related("authors")
    articles = {str(article.pk): article for article in eligible_articles}
    results = []
    for result in response.results:
        article = articles.get(result.document_id)
        if article is None:
            continue
        displayed_rank = len(results) + 1
        results.append(
            {
                "id": str(article.pk),
                "title": article.title,
                "abstract": article.abstract[:420],
                "authors": [author.name for author in article.authors.all()[:3]],
                "year": article.year,
                "venue": article.venue or article.source,
                "citation_count": article.citation_count,
                "is_open_access": article.is_open_access,
                "is_retracted": article.is_retracted,
                "paper_type": article.type,
                "doi": article.doi or "",
                "rank": displayed_rank,
                "retrieval_rank": result.rank,
                "score": round(result.score, 8),
                "explanation": {
                    "component_ranks": result.component_ranks,
                    "matched_terms": matched_query_terms(query, article),
                    "semantic_match": "specter2" in result.component_ranks,
                },
            }
        )
        if len(results) >= limit:
            break
    payload = {
        "query": query,
        "method": response.method,
        "components": response.components,
        "semantic_enabled": response.semantic_enabled,
        "degraded_reason": response.degraded_reason,
        "filters": search_filters,
        "cache_hit": False,
        "latency_ms": {
            "retrieval": round(response.total_latency_ms, 3),
            "components": {
                key: round(value, 3)
                for key, value in (response.component_latencies_ms or {}).items()
            },
        },
        "experiment": {
            "arm": experiment_arm,
            "status": expansion.status,
            "model": expansion.model,
            "prompt_version": expansion.prompt_version,
            "cache_hit": expansion.cache_hit,
            "latency_ms": round(expansion.latency_ms, 3),
            "input_tokens": expansion.input_tokens,
            "output_tokens": expansion.output_tokens,
            "cached_input_tokens": expansion.cached_input_tokens,
            "estimated_cost_usd": expansion.estimated_cost_usd,
            "provider_response_id": expansion.provider_response_id,
        },
        "results": results,
    }
    if request.user.is_staff:
        payload["experiment"]["expanded_query"] = expansion.query
    request_ms = (time.perf_counter() - request_started) * 1000
    payload["latency_ms"]["request"] = round(request_ms, 3)
    cache.set(cache_key, payload, settings.LIVE_SEARCH_CACHE_SECONDS)
    event_id = record_retrieval_event(
        request=request,
        query=query,
        actor_key=client_key,
        method=response.method,
        components=response.components,
        component_latencies_ms=response.component_latencies_ms or {},
        total_latency_ms=request_ms,
        results=results,
        semantic_enabled=response.semantic_enabled,
        degraded_reason=response.degraded_reason,
        cache_hit=False,
        experiment_arm=experiment_arm,
        expansion_status=expansion.status,
        expansion_model=expansion.model,
        expanded_query=expansion.query,
        expansion_prompt_version=expansion.prompt_version,
        expansion_cache_hit=expansion.cache_hit,
        expansion_latency_ms=expansion.latency_ms,
        expansion_input_tokens=expansion.input_tokens,
        expansion_output_tokens=expansion.output_tokens,
        expansion_cached_input_tokens=expansion.cached_input_tokens,
        expansion_estimated_cost_usd=expansion.estimated_cost_usd,
        expansion_provider_response_id=expansion.provider_response_id,
        search_filters=search_filters,
    )
    payload["request_id"] = event_id
    return JsonResponse(payload)


@require_POST
def api_retrieval_interaction(request):
    if len(request.body) > 16_384:
        return JsonResponse({"error": "interaction payload is too large"}, status=413)
    try:
        payload = json.loads(request.body or b"{}")
        event_type = str(payload.get("event_type", ""))
        request_id = str(payload.get("request_id", ""))
        if event_type == "impression":
            created, total = record_impressions(
                request=request,
                request_id=request_id,
                document_ids=payload.get("document_ids") or [],
            )
            return JsonResponse({"recorded": created, "received": total})
        interaction, created = record_interaction(
            request=request,
            request_id=request_id,
            document_id=str(payload.get("document_id", "")),
            event_type=event_type,
            relevance=payload.get("relevance"),
        )
        return JsonResponse(
            {"id": str(interaction.pk), "created": created, "event_type": event_type}
        )
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except (TypeError, ValidationError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse({"error": message}, status=400)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return round(ordered[index], 2)


def _evaluation_snapshot() -> dict:
    events = list(
        RetrievalEvent.objects.filter(Q(user__isnull=True) | Q(user__is_staff=False))
        .order_by("-created_at")[:5000]
    )
    event_by_id = {event.request_id: event for event in events}
    interactions = list(
        RetrievalInteraction.objects.filter(retrieval_event_id__in=event_by_id)
    )
    latencies = [event.total_latency_ms for event in events]
    arms = Counter(event.experiment_arm for event in events)
    methods = Counter(event.method for event in events)
    arm_summaries = []
    for arm, count in sorted(arms.items()):
        arm_events = [event for event in events if event.experiment_arm == arm]
        arm_event_ids = {event.request_id for event in arm_events}
        arm_interactions = [
            item for item in interactions if item.retrieval_event_id in arm_event_ids
        ]
        interaction_counts = Counter(item.event_type for item in arm_interactions)
        impressions = interaction_counts["impression"]
        judged = [item for item in arm_interactions if item.event_type == "relevance"]
        successful_requests = {
            item.retrieval_event_id
            for item in arm_interactions
            if item.event_type in {"click", "save"}
            or (item.event_type == "relevance" and item.relevance == 1)
        }
        arm_latencies = [event.total_latency_ms for event in arm_events]
        arm_summaries.append(
            {
                "name": arm,
                "count": count,
                "latency_p50_ms": round(median(arm_latencies), 2),
                "latency_p95_ms": _percentile(arm_latencies, 0.95),
                "failure_rate": round(
                    100
                    * sum(event.expansion_status == "provider_failed" for event in arm_events)
                    / count,
                    1,
                ),
                "ctr": round(100 * interaction_counts["click"] / impressions, 1)
                if impressions else 0.0,
                "save_rate": round(100 * interaction_counts["save"] / impressions, 1)
                if impressions else 0.0,
                "positive_relevance_rate": round(
                    100 * sum(item.relevance == 1 for item in judged) / len(judged), 1
                ) if judged else 0.0,
                "successful_search_rate": round(100 * len(successful_requests) / count, 1),
            }
        )
    interaction_counts = Counter(item.event_type for item in interactions)
    judged = [item for item in interactions if item.event_type == "relevance"]
    expanded_events = [
        event for event in events if event.experiment_arm == "llm_expansion"
    ]
    priced_expansions = [
        event.expansion_estimated_cost_usd
        for event in expanded_events
        if event.expansion_estimated_cost_usd is not None
    ]
    return {
        "event_count": len(events),
        "latency_p50_ms": round(median(latencies), 2) if latencies else 0.0,
        "latency_p95_ms": _percentile(latencies, 0.95),
        "cache_hit_rate": round(
            100 * sum(event.cache_hit for event in events) / len(events), 1
        ) if events else 0.0,
        "semantic_rate": round(
            100 * sum(event.semantic_enabled for event in events) / len(events), 1
        ) if events else 0.0,
        "arms": dict(arms),
        "arm_summaries": arm_summaries,
        "methods": dict(methods),
        "interactions": dict(interaction_counts),
        "positive_relevance_rate": round(
            100 * sum(item.relevance == 1 for item in judged) / len(judged), 1
        ) if judged else 0.0,
        "llm": {
            "request_count": len(expanded_events),
            "cache_hit_rate": round(
                100 * sum(event.expansion_cache_hit for event in expanded_events)
                / len(expanded_events),
                1,
            ) if expanded_events else 0.0,
            "input_tokens": sum(event.expansion_input_tokens for event in expanded_events),
            "output_tokens": sum(event.expansion_output_tokens for event in expanded_events),
            "estimated_cost_usd": round(sum(priced_expansions), 6)
            if priced_expansions else None,
        },
    }


def _event_outcomes(event: RetrievalEvent) -> dict:
    items = [item for item in event.interactions.all() if item.rank <= 10]
    counts = Counter(item.event_type for item in items)
    judgments = [item for item in items if item.event_type == "relevance"]
    positives = sum(item.relevance == 1 for item in judgments)
    return {
        "impressions": counts["impression"],
        "clicks": counts["click"],
        "saves": counts["save"],
        "judgments": len(judgments),
        "positive": positives,
        "success": bool(
            counts["click"] or counts["save"] or positives
        ),
    }


def _paired_query_comparisons(*, include_query_text: bool = True) -> dict:
    """Pair the latest staff baseline/LLM requests under identical conditions."""
    events = list(
        RetrievalEvent.objects.filter(
            user__is_staff=True,
            experiment_arm__in=("baseline", "llm_expansion"),
        )
        .select_related("user")
        .prefetch_related("interactions")
        .order_by("-created_at")[:2000]
    )
    grouped: dict[tuple, dict[str, list[RetrievalEvent]]] = {}
    for event in events:
        filters_key = json.dumps(
            event.search_filters or {}, sort_keys=True, separators=(",", ":")
        )
        key = (
            event.user_id,
            event.query_digest,
            event.protocol_sha256,
            filters_key,
        )
        grouped.setdefault(key, {"baseline": [], "llm_expansion": []})[
            event.experiment_arm
        ].append(event)

    pairs = []
    all_result_ids: set[str] = set()
    for (_, query_hash, protocol_hash, _), arms in grouped.items():
        if not arms["baseline"] or not arms["llm_expansion"]:
            continue
        llm = arms["llm_expansion"][0]
        baseline = min(
            arms["baseline"],
            key=lambda item: abs((item.created_at - llm.created_at).total_seconds()),
        )
        baseline_ids = [str(item) for item in baseline.result_ids[:10]]
        llm_ids = [str(item) for item in llm.result_ids[:10]]
        all_result_ids.update(baseline_ids)
        all_result_ids.update(llm_ids)
        common = set(baseline_ids) & set(llm_ids)
        union = set(baseline_ids) | set(llm_ids)
        baseline_outcomes = _event_outcomes(baseline)
        llm_outcomes = _event_outcomes(llm)
        cost = (
            float(llm.expansion_estimated_cost_usd)
            if llm.expansion_estimated_cost_usd is not None
            else None
        )
        pairs.append(
            {
                "pair_id": hashlib.sha256(
                    f"{baseline.request_id}:{llm.request_id}".encode("utf-8")
                ).hexdigest()[:12],
                "query": (
                    (llm.query_text or baseline.query_text or "").strip()
                    if include_query_text else ""
                ),
                "query_digest": query_hash,
                "protocol_sha256": protocol_hash,
                "search_filters": llm.search_filters or {},
                "created_at": max(baseline.created_at, llm.created_at),
                "gap_minutes": round(
                    abs((llm.created_at - baseline.created_at).total_seconds()) / 60,
                    1,
                ),
                "baseline": {
                    "request_id": str(baseline.request_id),
                    "latency_ms": round(baseline.total_latency_ms, 1),
                    "method": baseline.method,
                    "status": baseline.expansion_status,
                    "error": baseline.degraded_reason,
                    "cost_usd": 0.0,
                    "outcomes": baseline_outcomes,
                    "result_ids": baseline_ids,
                },
                "llm": {
                    "request_id": str(llm.request_id),
                    "latency_ms": round(llm.total_latency_ms, 1),
                    "expansion_latency_ms": round(llm.expansion_latency_ms, 1),
                    "method": llm.method,
                    "status": llm.expansion_status,
                    "error": llm.degraded_reason,
                    "model": llm.expansion_model,
                    "prompt_version": llm.expansion_prompt_version,
                    "cost_usd": cost,
                    "outcomes": llm_outcomes,
                    "result_ids": llm_ids,
                },
                "delta": {
                    "latency_ms": round(
                        llm.total_latency_ms - baseline.total_latency_ms, 1
                    ),
                    "positive": (
                        llm_outcomes["positive"] - baseline_outcomes["positive"]
                        if baseline_outcomes["judgments"]
                        and llm_outcomes["judgments"]
                        else None
                    ),
                },
                "overlap": {
                    "common_at_10": len(common),
                    "jaccard_at_10": round(len(common) / len(union), 3)
                    if union else 0.0,
                    "llm_only": len(set(llm_ids) - set(baseline_ids)),
                },
                "effectiveness_ready": bool(
                    baseline_outcomes["judgments"] and llm_outcomes["judgments"]
                ),
            }
        )

    title_by_id = {
        str(article.pk): article.title
        for article in Article.objects.filter(pk__in=all_result_ids)
    }
    for pair in pairs:
        for arm in (pair["baseline"], pair["llm"]):
            arm["results"] = [
                {
                    "id": document_id,
                    "title": title_by_id.get(document_id, document_id),
                    "rank": rank,
                }
                for rank, document_id in enumerate(arm.pop("result_ids"), start=1)
            ]

    pairs.sort(key=lambda item: item["created_at"], reverse=True)
    priced = [pair["llm"]["cost_usd"] for pair in pairs if pair["llm"]["cost_usd"] is not None]
    return {
        "pair_count": len(pairs),
        "judged_pair_count": sum(pair["effectiveness_ready"] for pair in pairs),
        "average_overlap_at_10": round(
            sum(pair["overlap"]["jaccard_at_10"] for pair in pairs) / len(pairs),
            3,
        ) if pairs else 0.0,
        "average_latency_delta_ms": round(
            sum(pair["delta"]["latency_ms"] for pair in pairs) / len(pairs), 1
        ) if pairs else 0.0,
        "provider_error_count": sum(
            pair["llm"]["status"] not in {"expanded"} for pair in pairs
        ),
        "estimated_cost_usd": round(sum(priced), 6) if priced else None,
        "pairs": pairs,
    }


@user_passes_test(lambda user: user.is_staff)
@require_GET
def evaluation_dashboard(request):
    paired = _paired_query_comparisons()
    return render(
        request,
        "frontend/evaluation_dashboard.html",
        {
            "online": _evaluation_snapshot(),
            "offline_runs": OfflineEvaluationRun.objects.all()[:50],
            "recent_events": RetrievalEvent.objects.select_related("user").order_by("-created_at")[:50],
            "expansion_enabled": settings.LLM_QUERY_EXPANSION_ENABLED,
            "expansion_traffic": settings.LLM_QUERY_EXPANSION_TRAFFIC_PERCENT,
            "expansion_staff_only": settings.LLM_QUERY_EXPANSION_STAFF_ONLY,
            "experiment_protocol": ExperimentProtocol.objects.order_by("-version").first(),
            "paired": paired,
        },
    )


@user_passes_test(lambda user: user.is_staff)
@require_GET
def evaluation_export(request):
    runs = OfflineEvaluationRun.objects.values(
        "run_key", "label", "method", "dataset", "split", "protocol",
        "metrics", "system_metrics", "query_count", "artifact_sha256", "is_frozen",
    )
    return JsonResponse(
        {
            "online": _evaluation_snapshot(),
            "paired": _paired_query_comparisons(include_query_text=False),
            "offline": list(runs),
        }
    )


@login_required
def library_list(request):
    libraries = (
        Library.objects.filter(user=request.user)
        .annotate(article_count=Count("articles"))
        .order_by("name")
    )
    return render(request, "frontend/library_list.html", {"object_list": libraries})


@login_required
def library_detail(request, pk):
    library = get_object_or_404(
        Library.objects.prefetch_related("articles__authors"),
        pk=pk,
        user=request.user,
    )
    if request.method == "POST":
        article = get_object_or_404(Article, pk=request.POST.get("id"))
        library.articles.remove(article)
        return redirect("library_detail", pk=library.pk)
    return render(request, "frontend/library_detail.html", {"object": library})


@login_required
def recommendations_page(request):
    return render(request, "frontend/your_rec.html")


@login_required
def topics(request):
    return render(
        request, "frontend/topics.html", {"disciplines": settings.SUBDISCIPLINES}
    )


def _updated_values(current, value: str, add: bool) -> list[str]:
    values = list(current or [])
    if add and value not in values:
        values.append(value)
    if not add and value in values:
        values.remove(value)
    return values


@login_required
@require_POST
def add_remove_topic(request):
    value = request.POST.get("tag", "").strip()
    if not value:
        return JsonResponse({"error": "tag is required"}, status=400)
    request.user.tags = _updated_values(
        request.user.tags, value, request.POST.get("add") == "1"
    )
    request.user.save(update_fields=["tags"])
    return JsonResponse({"tags": request.user.tags})


@login_required
@require_POST
def add_or_remove_kw(request):
    try:
        value = json.loads(request.POST.get("data", "{}"))["keywords"].strip()
    except (KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid keyword payload"}, status=400)
    request.user.keywords = _updated_values(
        request.user.keywords, value, request.POST.get("add") == "1"
    )
    request.user.save(update_fields=["keywords"])
    return JsonResponse({"keywords": request.user.keywords})


@login_required
@require_POST
def add_or_remove_author(request):
    try:
        value = json.loads(request.POST.get("data", "{}"))["authors"].strip()
    except (KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "invalid author payload"}, status=400)
    request.user.authors = _updated_values(
        request.user.authors, value, request.POST.get("add") == "1"
    )
    request.user.save(update_fields=["authors"])
    return JsonResponse({"authors": request.user.authors})


class GetAuthor(DetailView):
    model = Authors
    template_name = "frontend/author.html"

    def get_queryset(self):
        return Authors.objects.prefetch_related("article_set__authors")


@login_required
@require_POST
def load_articles_author(request, pk):
    author = get_object_or_404(Authors, pk=pk)
    if not settings.MENDELEY_ID or not settings.MENDELEY_SECRET:
        return JsonResponse({"error": "Mendeley is not configured"}, status=503)
    article_ids = get_article_from_authors(
        author.name, get_mendeley_access_token()
    )
    return JsonResponse({"article_ids": article_ids})


def _search_facets() -> dict:
    facets = cache.get("search:facets:v1")
    if facets is not None:
        return facets
    paper_types = list(
        Article.objects.exclude(type="")
        .values_list("type", flat=True)
        .distinct()
        .order_by("type")[:30]
    )
    sources = set(
        Article.objects.exclude(source="")
        .values_list("source", flat=True)
        .distinct()[:80]
    )
    sources.update(
        Article.objects.exclude(venue="")
        .values_list("venue", flat=True)
        .distinct()[:80]
    )
    facets = {"paper_types": paper_types, "sources": sorted(sources)[:80]}
    cache.set("search:facets:v1", facets, 900)
    return facets


def _search_context(request, *, query: str, article_list) -> dict:
    libraries = []
    if request.user.is_authenticated:
        libraries = list(
            Library.objects.filter(user=request.user)
            .annotate(article_count=Count("articles"))
            .order_by("name")
        )
    return {
        "article_list": article_list,
        "query": query,
        "filters": parse_search_filters(request.GET, strict=False),
        "search_facets": _search_facets(),
        "search_libraries": libraries,
        "staff_expansion_available": (
            request.user.is_staff and settings.LLM_QUERY_EXPANSION_ENABLED
        ),
    }


@ensure_csrf_cookie
@require_GET
def search(request):
    query = (request.GET.get("query") or request.GET.get("search") or "").strip()
    if not query:
        return render(
            request,
            "frontend/search.html",
            _search_context(request, query="", article_list=[]),
        )
    search_filters = parse_search_filters(request.GET, strict=False)
    article_list = Article.objects.filter(
        Q(title__icontains=query)
        | Q(abstract__icontains=query)
        | Q(source__icontains=query)
        | Q(authors__name__icontains=query)
    ).distinct()
    article_list = (
        apply_search_filters(article_list, search_filters)
        .prefetch_related("authors")
        .order_by("-citation_count", "-year")[:100]
    )
    return render(
        request,
        "frontend/search.html",
        _search_context(request, query=query, article_list=article_list),
    )


@login_required
@require_POST
def add_library(request):
    name = request.POST.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)
    library, created = Library.objects.get_or_create(user=request.user, name=name)
    return JsonResponse(
        {"id": library.pk, "name": library.name}, status=201 if created else 200
    )


@login_required
@require_POST
def delete_library(request):
    library = get_object_or_404(
        Library, pk=request.POST.get("lib_id"), user=request.user
    )
    library.delete()
    return JsonResponse({"success": True})


@login_required
@require_POST
def add_to_library(request):
    library = get_object_or_404(
        Library, pk=request.POST.get("library_id"), user=request.user
    )
    article = get_object_or_404(Article, pk=request.POST.get("article_id"))
    library.articles.add(article)
    request_id = request.POST.get("request_id", "").strip()
    interaction_source = request.POST.get("source", "paper_detail").strip()
    if interaction_source not in {"paper_detail", "search_results"}:
        interaction_source = "paper_detail"
    if request_id:
        try:
            record_interaction(
                request=request,
                request_id=request_id,
                document_id=str(article.pk),
                event_type="save",
                source=interaction_source,
            )
        except (PermissionDenied, ValidationError):
            logger.info("Ignored invalid save attribution for article %s", article.pk)
    return JsonResponse({"success": True})


class DetailArticle(DetailView):
    model = Article
    template_name = "frontend/detail.html"

    def get_queryset(self):
        return Article.objects.prefetch_related("authors", "comment_set__user")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.object.retrieval_text
        if query:
            ids = get_similar_items(query, start=0, end=21)
            ids = [
                article_id
                for article_id in ids
                if article_id != str(self.object.pk)
            ][:8]
            context["similar_items"] = _ordered_articles(ids)
        else:
            context["similar_items"] = []
        if self.request.user.is_authenticated:
            context["libraries"] = (
                Library.objects.filter(user=self.request.user)
                .annotate(article_count=Count("articles"))
                .order_by("name")
            )
        else:
            context["libraries"] = []
        return context

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication required"}, status=401)
        self.object = self.get_object()
        body = request.POST.get("comment", "").strip()
        if not body:
            return JsonResponse({"error": "comment is required"}, status=400)
        self.object.comment_set.create(user=request.user, body=body)
        return redirect("article", pk=self.object.pk)


@require_GET
def article_api(request, pk):
    return JsonResponse(get_object_or_404(Article, pk=pk).get_json())


@require_GET
def get_readers(request, id):
    get_object_or_404(Article, pk=id)
    return JsonResponse({"readers": {}, "readers_by_sub": {}})


@login_required
@require_POST
def update_review(request):
    article = get_object_or_404(Article, pk=request.POST.get("article_id"))
    try:
        rating = int(request.POST.get("rating", "0"))
    except ValueError:
        return JsonResponse({"error": "rating must be 1 or -1"}, status=400)
    if rating not in {-1, 1}:
        return JsonResponse({"error": "rating must be 1 or -1"}, status=400)
    review, _ = Review.objects.update_or_create(
        user=request.user, article=article, defaults={"rating": rating}
    )
    return JsonResponse({"rating": review.rating})


@login_required
@require_POST
def get_recommendation(request):
    query = request.POST.get("query", "").strip()
    if not query:
        return JsonResponse({"error": "query is required"}, status=400)
    ids = get_similar_items(query, end=100)
    return JsonResponse(
        [_article_payload(article) for article in _ordered_articles(ids)], safe=False
    )


@require_GET
def api_new_articles(request):
    articles = Article.objects.order_by("-year", "-add_on")[:20]
    return JsonResponse([_article_payload(article) for article in articles], safe=False)


@require_GET
def api_top_articles(request):
    articles = Article.objects.order_by("-count", "-score")[:20]
    return JsonResponse([_article_payload(article) for article in articles], safe=False)


@require_GET
def api_hot_articles(request):
    articles = Article.objects.order_by("-score", "-count")[:20]
    return JsonResponse([_article_payload(article) for article in articles], safe=False)


@login_required
@require_GET
def get_library_recommendation(request, pk):
    library = get_object_or_404(Library, pk=pk, user=request.user)
    seed_text = " ".join(library.articles.values_list("title", flat=True)[:20]).strip()
    if not seed_text:
        return JsonResponse([], safe=False)
    ids = get_similar_items(seed_text, end=50)
    seen = {
        str(article_id)
        for article_id in library.articles.values_list("pk", flat=True)
    }
    ids = [article_id for article_id in ids if article_id not in seen]
    return JsonResponse(
        [_article_payload(article) for article in _ordered_articles(ids)], safe=False
    )


def about(request):
    stats = cache.get("about:corpus-stats:v1")
    if stats is None:
        stats = {
            "papers": Article.objects.count(),
            "authors": Authors.objects.count(),
            "sources": Article.objects.exclude(source="")
            .values("source")
            .distinct()
            .count(),
            "open_access": Article.objects.filter(is_open_access=True).count(),
        }
        cache.set("about:corpus-stats:v1", stats, 900)
    return render(request, "frontend/about.html", {"about_stats": stats})


def profile(request):
    return redirect("questions" if request.user.is_authenticated else "login")


def change_lan(request, lan):
    supported = {code for code, _ in settings.LANGUAGES}
    language = lan if lan in supported else settings.LANGUAGE_CODE
    translation.activate(language)
    request.session["lan"] = language
    response = redirect("home")
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=60 * 60 * 24 * 365,
        secure=not settings.DEBUG,
        samesite="Lax",
    )
    return response
