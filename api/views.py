from __future__ import annotations

import requests
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from frontend.utils import (
    MENDELEY_SEARCH_URL,
    REQUEST_TIMEOUT,
    get_mendeley_access_token,
)


def index(request):
    try:
        request.session["mendeley_access_token"] = get_mendeley_access_token()
    except (RuntimeError, requests.RequestException) as exc:
        return HttpResponse(f"Mendeley authentication failed: {exc}", status=503)
    return redirect("list_documents")


def auth_return(request):
    return HttpResponse(
        "Authorization-code flow is not enabled; catalog access uses client credentials.",
        status=501,
    )


def _headers(request) -> dict[str, str] | None:
    token = request.session.get("mendeley_access_token")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.mendeley-document.1+json",
    }


@require_GET
def list_documents(request):
    headers = _headers(request)
    if headers is None:
        return redirect("index")
    query = request.GET.get("query", "information retrieval")
    response = requests.get(
        MENDELEY_SEARCH_URL,
        headers=headers,
        params={"query": query, "limit": 25, "view": "all"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 401:
        request.session.pop("mendeley_access_token", None)
        return redirect("index")
    response.raise_for_status()
    return render(
        request, "api/library.html", {"docs": response.json(), "query": query}
    )


@require_GET
def get_document(request, doc_id):
    headers = _headers(request)
    if headers is None:
        return redirect("index")
    response = requests.get(
        f"https://api.mendeley.com/catalog/{doc_id}",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return render(request, "api/metadata.html", {"doc": response.json()})
