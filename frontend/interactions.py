from __future__ import annotations

from collections.abc import Iterable

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from api.models import Article, RetrievalEvent, RetrievalInteraction


PUBLIC_EVENTS = {"impression", "click"}
AUTHENTICATED_EVENTS = {"save", "relevance"}


def _validated_event(request, request_id: str) -> RetrievalEvent:
    try:
        event = RetrievalEvent.objects.get(request_id=request_id)
    except (RetrievalEvent.DoesNotExist, ValueError) as exc:
        raise ValidationError("unknown retrieval request") from exc
    if event.user_id and (
        not request.user.is_authenticated or event.user_id != request.user.pk
    ):
        raise PermissionDenied("retrieval request belongs to another user")
    return event


def _validated_rank(event: RetrievalEvent, document_id: str) -> int:
    document_id = str(document_id)
    try:
        return [str(value) for value in event.result_ids].index(document_id) + 1
    except ValueError as exc:
        raise ValidationError("document was not exposed by this request") from exc


@transaction.atomic
def record_interaction(
    *,
    request,
    request_id: str,
    document_id: str,
    event_type: str,
    relevance: int | None = None,
    source: str = "live_search",
) -> tuple[RetrievalInteraction, bool]:
    if event_type not in PUBLIC_EVENTS | AUTHENTICATED_EVENTS:
        raise ValidationError("unsupported interaction type")
    if event_type in AUTHENTICATED_EVENTS and not request.user.is_authenticated:
        raise PermissionDenied("authentication required for this interaction")
    if event_type == "relevance" and relevance not in {-1, 1}:
        raise ValidationError("relevance must be -1 or 1")
    if event_type != "relevance":
        relevance = None

    event = _validated_event(request, request_id)
    document_id = str(document_id)
    rank = _validated_rank(event, document_id)
    article = Article.objects.filter(pk=document_id).first()
    interaction, created = RetrievalInteraction.objects.update_or_create(
        retrieval_event=event,
        document_id=document_id,
        event_type=event_type,
        defaults={
            "article": article,
            "user": request.user if request.user.is_authenticated else None,
            "rank": rank,
            "relevance": relevance,
            "metadata": {"source": source},
        },
    )
    return interaction, created


def record_impressions(
    *, request, request_id: str, document_ids: Iterable[str]
) -> tuple[int, int]:
    values = list(dict.fromkeys(str(value) for value in document_ids))
    if not values or len(values) > 20:
        raise ValidationError("impressions must contain between 1 and 20 documents")
    event = _validated_event(request, request_id)
    ranks = {document_id: _validated_rank(event, document_id) for document_id in values}
    existing = set(
        RetrievalInteraction.objects.filter(
            retrieval_event=event,
            event_type="impression",
            document_id__in=values,
        ).values_list("document_id", flat=True)
    )
    pending = [document_id for document_id in values if document_id not in existing]
    articles = Article.objects.in_bulk(pending)
    RetrievalInteraction.objects.bulk_create(
        [
            RetrievalInteraction(
                retrieval_event=event,
                article=articles.get(document_id),
                document_id=document_id,
                user=request.user if request.user.is_authenticated else None,
                event_type="impression",
                rank=ranks[document_id],
                metadata={"source": "live_search"},
            )
            for document_id in pending
        ],
        ignore_conflicts=True,
    )
    return len(pending), len(values)
