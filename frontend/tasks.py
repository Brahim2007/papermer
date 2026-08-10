from __future__ import annotations

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string

from api.models import Article

from .recom import get_similar_items


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_recommendation_emails() -> dict[str, int]:
    sent = 0
    skipped = 0
    for user in get_user_model().objects.filter(is_active=True).iterator():
        queries = [
            *(user.keywords or []),
            *(user.tags or []),
            *(user.authors or []),
        ]
        fused: dict[str, float] = {}
        for query in dict.fromkeys(queries):
            for rank, article_id in enumerate(
                get_similar_items(query, end=50), start=1
            ):
                fused[article_id] = fused.get(article_id, 0.0) + 1.0 / (60 + rank)

        ordered_ids = sorted(fused, key=fused.get, reverse=True)[:10]
        articles = Article.objects.in_bulk(ordered_ids)
        recommendations = [
            {
                "title": articles[article_id].title,
                "id": article_id,
                "score": fused[article_id],
            }
            for article_id in ordered_ids
            if article_id in articles
        ]
        if not recommendations or not user.email:
            skipped += 1
            continue

        content = render_to_string(
            "mail_recommendations.html",
            {"recommendations": recommendations, "user": user},
        )
        send_mail(
            "Your PaperMetrix recommendations",
            content,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=content,
        )
        sent += 1
    return {"sent": sent, "skipped": skipped}


# Historical Celery Beat schedules referenced ``frontend.tasks.add``.
add = send_recommendation_emails
