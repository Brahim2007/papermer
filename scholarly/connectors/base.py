from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock
from time import monotonic, sleep
from typing import Any

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scholarly.schema import CanonicalWorkRecord


class ConnectorRequestError(RuntimeError):
    """A provider request failed after bounded retries."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaseConnector(ABC):
    source: str

    def __init__(
        self,
        *,
        timeout: tuple[int, int] = (5, 30),
        min_interval_seconds: float = 0.0,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        self.timeout = timeout
        self.min_interval_seconds = min_interval_seconds
        self._request_lock = Lock()
        self._last_request_started = 0.0
        self.session = requests.Session()
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        try:
            with self._request_lock:
                wait_seconds = self.min_interval_seconds - (
                    monotonic() - self._last_request_started
                )
                if wait_seconds > 0:
                    sleep(wait_seconds)
                self._last_request_started = monotonic()
                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            status_code = response.status_code if response is not None else None
            status = status_code if status_code is not None else "unavailable"
            if status in {401, 403}:
                guidance = "verify that the provider API key is active and authorized"
            elif status == 429:
                guidance = "reduce request rate or wait for the provider quota to reset"
            else:
                guidance = "configure the provider credentials and retry later"
            raise ConnectorRequestError(
                f"{self.source} request failed (HTTP status: {status}); "
                f"{guidance}",
                status_code=status_code,
            ) from exc

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._get(url, params=params, headers=headers).json()

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        return self._get(url, params=params, headers=headers).text

    @abstractmethod
    def search(self, query: str, *, limit: int = 25) -> list[CanonicalWorkRecord]:
        raise NotImplementedError
