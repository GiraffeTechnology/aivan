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
_dependency_probes: Counter[tuple[str, str, str]] = Counter()
_dependency_duration_seconds: dict[tuple[str, str], float] = defaultdict(float)


async def record_request_metrics(request: Request, call_next):
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        status_class = "5xx" if response is None else f"{response.status_code // 100}xx"
        elapsed = time.perf_counter() - started
        with _lock:
            _requests[(request.method, route_path, status_class)] += 1
            _duration_seconds[(request.method, route_path)] += elapsed


def record_dependency_probe(
    *, dependency_id: str, criticality: str, status: str, duration_seconds: float
) -> None:
    with _lock:
        _dependency_probes[(dependency_id, criticality, status)] += 1
        _dependency_duration_seconds[(dependency_id, criticality)] += max(
            0.0, duration_seconds
        )


def _context(request: Request) -> RequestContext:
    return resolve_request_context(request)


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@router.get("/metrics")
def metrics(_: RequestContext = Depends(_context)):
    return Response(_render_metrics(), media_type="text/plain; version=0.0.4")


def _render_metrics() -> str:
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
        lines.extend(
            [
                "# HELP aivan_dependency_probe_total Dependency probes by stable service identifier.",
                "# TYPE aivan_dependency_probe_total counter",
            ]
        )
        for (dependency_id, criticality, status), count in sorted(_dependency_probes.items()):
            labels = (
                f'dependency="{_label(dependency_id)}",criticality="{_label(criticality)}",'
                f'status="{_label(status)}"'
            )
            lines.append(f"aivan_dependency_probe_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP aivan_dependency_probe_duration_seconds_sum Cumulative probe duration.",
                "# TYPE aivan_dependency_probe_duration_seconds_sum counter",
            ]
        )
        for (dependency_id, criticality), duration in sorted(
            _dependency_duration_seconds.items()
        ):
            labels = (
                f'dependency="{_label(dependency_id)}",criticality="{_label(criticality)}"'
            )
            lines.append(
                f"aivan_dependency_probe_duration_seconds_sum{{{labels}}} {duration:.6f}"
            )
    return "\n".join(lines) + "\n"


def _reset_metrics_for_tests() -> None:
    with _lock:
        _requests.clear()
        _duration_seconds.clear()
        _dependency_probes.clear()
        _dependency_duration_seconds.clear()
