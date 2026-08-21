from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Request, Response

from aivan.api.request_context import RequestContext, resolve_request_context


router = APIRouter(tags=["observability"])
_lock = threading.Lock()
_requests: Counter[tuple[str, str, str]] = Counter()
_duration_seconds: dict[tuple[str, str], float] = defaultdict(float)


async def record_request_metrics(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    status_class = f"{response.status_code // 100}xx"
    elapsed = time.perf_counter() - started
    with _lock:
        _requests[(request.method, route_path, status_class)] += 1
        _duration_seconds[(request.method, route_path)] += elapsed
    return response


def _context(request: Request) -> RequestContext:
    return resolve_request_context(request)


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@router.get("/metrics")
def metrics(_: RequestContext = Depends(_context)):
    lines = [
        "# HELP aivan_http_requests_total HTTP requests by stable route template.",
        "# TYPE aivan_http_requests_total counter",
    ]
    with _lock:
        for (method, route, status_class), count in sorted(_requests.items()):
            labels = f'method="{_label(method)}",route="{_label(route)}",status_class="{status_class}"'
            lines.append(f"aivan_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP aivan_http_request_duration_seconds_sum Cumulative request duration.",
                "# TYPE aivan_http_request_duration_seconds_sum counter",
            ]
        )
        for (method, route), duration in sorted(_duration_seconds.items()):
            labels = f'method="{_label(method)}",route="{_label(route)}"'
            lines.append(f"aivan_http_request_duration_seconds_sum{{{labels}}} {duration:.6f}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
