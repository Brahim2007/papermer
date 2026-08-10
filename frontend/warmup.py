from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


_lock = threading.Lock()
_state = {
    "status": "idle",
    "latency_ms": 0.0,
    "semantic_enabled": False,
    "degraded_reason": "",
    "updated_at": "",
}


def semantic_warmup_status() -> dict:
    with _lock:
        return dict(_state)


def run_semantic_warmup(query: str) -> dict:
    from frontend.recom import live_search

    with _lock:
        if _state["status"] in {"warming", "ready"}:
            return dict(_state)
        _state.update(status="warming", updated_at=datetime.now(timezone.utc).isoformat())
    started = time.perf_counter()
    try:
        response = live_search(query, top_k=1)
        status = "ready" if response.semantic_enabled else "failed"
        degraded_reason = response.degraded_reason or ""
        semantic_enabled = response.semantic_enabled
    except Exception as exc:
        status = "failed"
        degraded_reason = type(exc).__name__
        semantic_enabled = False
    with _lock:
        _state.update(
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            semantic_enabled=semantic_enabled,
            degraded_reason=degraded_reason,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return dict(_state)
