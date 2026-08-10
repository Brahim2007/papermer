from __future__ import annotations

from django.db import DatabaseError, connection
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def _response(payload: dict, *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def liveness(request):
    return _response({"status": "ok"})


@require_GET
def readiness(request):
    checks = {"database": "ok"}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return _response(
            {"status": "unavailable", "checks": {"database": "failed"}},
            status=503,
        )
    if settings.SEMANTIC_SEARCH_WARMUP_QUERY:
        from frontend.warmup import semantic_warmup_status

        semantic = semantic_warmup_status()
        checks["semantic_search"] = semantic
        if (
            settings.SEMANTIC_SEARCH_REQUIRE_WARM_READY
            and semantic["status"] != "ready"
        ):
            return _response(
                {"status": "warming", "checks": checks},
                status=503,
            )
    return _response({"status": "ready", "checks": checks})
