from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from api.models import Article, Tag

from .recom import get_explanation, get_similar_items
from .utils import twitter_from_doi


@login_required
@require_POST
def get_article_from_data(request):
    queries = [
        query.strip()
        for query in request.POST.get("query", "").split(";")
        if query.strip()
    ]
    response_data = {"recommendations": [], "explanations": []}
    for query in queries:
        recommended = get_similar_items(query, end=20)
        response_data["recommendations"].append(recommended)
        response_data["explanations"].append(
            get_explanation(recommended, query=query)
        )
    return JsonResponse(response_data)


@login_required
@require_POST
def add_tag(request, pk):
    article = get_object_or_404(Article, pk=pk)
    value = request.POST.get("tag", "").strip()
    if not value:
        return JsonResponse({"error": "tag is required"}, status=400)
    tag, _ = Tag.objects.get_or_create(tag=value, user=request.user)
    tag.article.add(article)
    return JsonResponse({"tag": tag.tag, "pk": tag.pk}, status=201)


@login_required
@require_POST
def remove_tag(request, pk):
    tag = get_object_or_404(Tag, pk=pk, user=request.user)
    article_id = request.POST.get("article_id")
    if article_id:
        tag.article.remove(get_object_or_404(Article, pk=article_id))
    else:
        tag.delete()
    return JsonResponse({"success": True})


@require_GET
def get_tweets(request, pk):
    article = get_object_or_404(Article, pk=pk)
    tweets = article.twitter_data.get("tweets")
    if tweets is None:
        tweets = twitter_from_doi(article.title, article.identifiers.get("doi"))
        article.twitter_data = {"tweets": tweets}
        article.save(update_fields=["twitter_data"])
    return JsonResponse({"tweets": tweets})
