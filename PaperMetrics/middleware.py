from __future__ import annotations

import hashlib
import hmac
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse


logger = logging.getLogger(__name__)


class AuthRateLimitMiddleware:
    """Small Redis-backed guard for public authentication POST endpoints."""

    LIMITS = {
        "/auth/login/": (10, 300),
        "/auth/signup/": (5, 3600),
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        segments = path.split("/", 2)
        supported_languages = {code for code, _ in settings.LANGUAGES}
        if len(segments) == 3 and segments[1] in supported_languages:
            path = f"/{segments[2]}"
        limit = self.LIMITS.get(path)
        if request.method == "POST" and limit:
            maximum, window = limit
            if self._exceeded(
                request,
                maximum=maximum,
                window=window,
                rate_path=path,
            ):
                response = JsonResponse(
                    {"detail": "Too many attempts. Try again later."},
                    status=429,
                )
                response["Retry-After"] = str(window)
                response["Cache-Control"] = "no-store"
                return response
        return self.get_response(request)

    @staticmethod
    def _client_address(request) -> str:
        if settings.TRUST_PROXY_HEADERS:
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")

    def _exceeded(
        self,
        request,
        *,
        maximum: int,
        window: int,
        rate_path: str,
    ) -> bool:
        address = self._client_address(request)
        digest = hmac.new(
            settings.SECRET_KEY.encode(),
            address.encode(),
            hashlib.sha256,
        ).hexdigest()
        path_digest = hashlib.sha256(rate_path.encode()).hexdigest()[:12]
        key = f"auth-rate:{path_digest}:{digest}"
        try:
            if cache.add(key, 1, timeout=window):
                return False
            return cache.incr(key) > maximum
        except Exception:
            logger.exception("Authentication rate-limit cache unavailable")
            return False
