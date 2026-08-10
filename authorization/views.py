from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from api.models import Article, Library
from frontend.recom import get_similar_items

from .forms import LoginForm, SignupForm


def sign_up(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        Library.objects.get_or_create(name="Reading list", user=user)
        login(request, user)
        messages.success(
            request,
            _("Your account is ready. Add a few interests to improve your recommendations."),
        )
        return redirect("questions")
    return render(request, "auth/signup.html", {"form": form})


@login_required
def signup_questions(request):
    return render(
        request,
        "auth/questions.html",
        {"disciplines": settings.SUBDISCIPLINES},
    )


def login_(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        if user is not None:
            login(request, user)
            if not form.cleaned_data["remember_me"]:
                request.session.set_expiry(0)
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect("home")
        error = _("The email address or password is incorrect.")
    return render(request, "auth/login.html", {"form": form, "error": error})


@require_POST
def logout_(request):
    logout(request)
    messages.success(request, _("You have been signed out safely."))
    return redirect("home")


@login_required
@require_GET
def get_recommendation_user(request):
    queries = [
        *(request.user.keywords or []),
        *(request.user.tags or []),
        *(request.user.authors or []),
    ]
    if not queries:
        return JsonResponse([], safe=False)

    # Reciprocal-rank fusion avoids comparing uncalibrated scores from
    # independent user-profile queries and removes duplicate papers.
    fused_scores: dict[str, float] = {}
    signal_ranks: dict[str, dict[str, int]] = {}
    for query in dict.fromkeys(queries):
        for rank, article_id in enumerate(
            get_similar_items(query=query, start=0, end=100), start=1
        ):
            fused_scores[article_id] = fused_scores.get(article_id, 0.0) + 1.0 / (
                60 + rank
            )
            signal_ranks.setdefault(article_id, {})[query] = rank

    ordered_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    articles = Article.objects.in_bulk(ordered_ids)
    payload = []
    for article_id in ordered_ids:
        if article_id not in articles:
            continue
        ranked_signals = sorted(
            signal_ranks.get(article_id, {}).items(), key=lambda item: (item[1], item[0])
        )
        payload.append(
            {
                "title": articles[article_id].title,
                "id": article_id,
                "score": fused_scores[article_id],
                "method": "profile_tfidf_rrf",
                "explanation": {
                    "matched_signal_count": len(ranked_signals),
                    "signals": [
                        {"label": signal, "rank": rank}
                        for signal, rank in ranked_signals[:3]
                    ],
                    "reason_code": (
                        "multiple_profile_signals"
                        if len(ranked_signals) > 1
                        else "single_profile_signal"
                    ),
                },
            }
        )
    return JsonResponse(payload, safe=False)
