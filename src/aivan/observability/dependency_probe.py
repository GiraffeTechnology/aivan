"""Versioned, provider-neutral health probes and production side-effect gate.

Probe results deliberately contain no endpoint, response body, credentials, or
raw exception text.  They are point-in-time observations only; durable alert
state belongs to the future giraffe-db-backed B1-B contract.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, wait
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Literal, cast

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from aivan.governance.runtime_policy import is_production, reject_test_transport_in_production
from aivan.gpm.persistence_contract import GPM_PERSISTENCE_CONTRACT_VERSION
from aivan.observability.metrics import record_dependency_probe
from aivan.observability.mutation_policy import (
    mutation_classification,
    mutation_policy_entries,
)


ProbeStatus = Literal[
    "ready",
    "misconfigured",
    "unavailable",
    "timeout",
    "invalid_response",
    "incompatible",
    "stale",
]
Criticality = Literal["critical", "optional"]
HeaderContract = Literal["generic", "giraffe-db"]

_SAFE_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
_SAFE_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$")
MAX_REQUIRED_DEPENDENCIES = 4
MAX_HTTP_REQUESTS_PER_DEPENDENCY = 2
MAX_CONCURRENT_PROBE_TASKS = 4
_PROBE_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_PROBE_TASKS,
    thread_name_prefix="aivan-dependency-probe",
)
_PROBE_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_PROBE_TASKS)


class _InvalidProbeResponse(ValueError):
    pass


@dataclass(frozen=True)
class DependencyProbeSpec:
    dependency_id: str
    owner: str
    endpoint_class: str
    base_url_env: str
    expected_version_env: str
    health_path: str
    version_path: str
    timeout_seconds: float
    stale_after_seconds: float
    criticality: Criticality
    auth_header_name: str | None = None
    auth_value_env: str | None = None
    header_contract: HeaderContract = "generic"
    response_tenant_env: str | None = None
    version_keys: tuple[str, ...] = (
        "contract_version",
        "api_version",
        "version",
        "gpm_contract_version",
    )
    contract_version: str = "aivan.dependency-probe-spec.v1"


@dataclass(frozen=True)
class DependencyProbeResult:
    dependency_id: str
    contract_version: str
    criticality: Criticality
    owner: str
    expected_version: str | None
    observed_version: str | None
    status: ProbeStatus
    error_code: str | None
    correlation_id: str
    checked_at_epoch: float
    duration_seconds: float
    stale_after_seconds: float

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def is_ready_at(self, now_epoch: float | None = None) -> bool:
        now = time.time() if now_epoch is None else now_epoch
        return self.ready and 0 <= now - self.checked_at_epoch <= self.stale_after_seconds

    def to_public_dict(self, *, now_epoch: float | None = None) -> dict[str, object]:
        status: ProbeStatus = self.status
        error_code = self.error_code
        if self.ready and not self.is_ready_at(now_epoch):
            status = "stale"
            error_code = "DEPENDENCY_PROBE_STALE"
        return {
            "dependency_id": self.dependency_id,
            "contract_version": self.contract_version,
            "criticality": self.criticality,
            "owner": self.owner,
            "expected_version": self.expected_version,
            "observed_version": self.observed_version,
            "status": status,
            "error_code": error_code,
            "correlation_id": self.correlation_id,
            "checked_at_epoch": self.checked_at_epoch,
            "duration_seconds": self.duration_seconds,
            "stale_after_seconds": self.stale_after_seconds,
        }


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def probe_total_timeout_seconds() -> float:
    """Maximum wall-time budget for one four-provider probe fan-out."""

    return _positive_float("AIVAN_DEPENDENCY_PROBE_TOTAL_TIMEOUT_SECONDS", 6.0)


def required_dependency_specs() -> tuple[DependencyProbeSpec, ...]:
    """Return the frozen B1-A probe declarations, never provider instances."""

    definitions = (
        (
            "giraffe-db",
            "DB",
            "tenant-data-contract",
            "GIRAFFE_DB_BASE_URL",
            "AIVAN_GIRAFFE_DB_EXPECTED_VERSION",
            "/healthz",
            "/api/data/schema-version",
            "GIRAFFE_DB_PROBE_TIMEOUT_SECONDS",
            "GIRAFFE_DB_PROBE_STALE_SECONDS",
            "X-Service-Auth",
            "GIRAFFE_DB_SERVICE_AUTH_SECRET",
            ("gpm_contract_version", "contract_version", "schema_version"),
            "giraffe-db",
            "AIVAN_DEPENDENCY_PROBE_TENANT_ID",
        ),
        (
            "gltg",
            "GLTG",
            "lead-time-service",
            "GLTG_API_BASE_URL",
            "AIVAN_GLTG_EXPECTED_VERSION",
            "/health",
            "/version",
            "GLTG_PROBE_TIMEOUT_SECONDS",
            "GLTG_PROBE_STALE_SECONDS",
            None,
            None,
            ("api_version", "version", "contract_version"),
            "generic",
            None,
        ),
        (
            "openclaw",
            "OpenClaw",
            "managed-outbound-gateway",
            "OPENCLAW_BASE_URL",
            "AIVAN_OPENCLAW_EXPECTED_VERSION",
            "/healthz",
            "/healthz",
            "OPENCLAW_PROBE_TIMEOUT_SECONDS",
            "OPENCLAW_PROBE_STALE_SECONDS",
            "X-OpenClaw-Key",
            "OPENCLAW_API_KEY",
            ("contract_version", "api_version", "version"),
            "generic",
            None,
        ),
        (
            "giraffe-language-skill",
            "giraffe-language-skill",
            "authoritative-translation-service",
            "AIVAN_LANGUAGE_SKILL_BASE_URL",
            "AIVAN_LANGUAGE_SKILL_EXPECTED_VERSION",
            "/healthz",
            "/v1/models",
            "AIVAN_LANGUAGE_SKILL_PROBE_TIMEOUT_SECONDS",
            "AIVAN_LANGUAGE_SKILL_PROBE_STALE_SECONDS",
            None,
            None,
            ("contract_version", "api_version", "version"),
            "generic",
            None,
        ),
    )
    specs: list[DependencyProbeSpec] = []
    for (
        dependency_id,
        owner,
        endpoint_class,
        base_url_env,
        expected_version_env,
        health_path,
        version_path,
        timeout_env,
        stale_env,
        auth_header_name,
        auth_value_env,
        version_keys,
        header_contract,
        response_tenant_env,
    ) in definitions:
        timeout = _positive_float(timeout_env, 3.0)
        stale = max(_positive_float(stale_env, 30.0), timeout)
        specs.append(
            DependencyProbeSpec(
                dependency_id=dependency_id,
                owner=owner,
                endpoint_class=endpoint_class,
                base_url_env=base_url_env,
                expected_version_env=expected_version_env,
                health_path=health_path,
                version_path=version_path,
                timeout_seconds=timeout,
                stale_after_seconds=stale,
                criticality="critical",
                auth_header_name=auth_header_name,
                auth_value_env=auth_value_env,
                header_contract=cast(HeaderContract, header_contract),
                response_tenant_env=response_tenant_env,
                version_keys=version_keys,
            )
        )
    return tuple(specs)


def _correlation_id(value: str | None) -> str:
    candidate = (value or "").strip()
    return candidate if _SAFE_CORRELATION.fullmatch(candidate) else f"trace_{uuid.uuid4().hex}"


def _probe_url(base_url: str, path: str) -> httpx.URL:
    parsed = httpx.URL(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError("invalid service URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials forbidden in service URL")
    base_path = parsed.path.rstrip("/")
    return parsed.copy_with(path=f"{base_path}/{path.lstrip('/')}")


def _version(payload: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return None


def _response_object(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise _InvalidProbeResponse from exc
    if not isinstance(payload, dict):
        raise _InvalidProbeResponse
    return payload


def _health_ready(payload: dict[str, object]) -> bool:
    for key in ("ready", "healthy"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    status = payload.get("status")
    return isinstance(status, str) and status.strip().lower() in {
        "ok",
        "ready",
        "healthy",
        "up",
        "pass",
        "passed",
    }


def _trusted_probe_tenant(spec: DependencyProbeSpec) -> str:
    if spec.header_contract != "giraffe-db":
        return ""
    explicit = os.environ.get(spec.response_tenant_env or "", "").strip()
    tenant = explicit or os.environ.get("AIVAN_TENANT_ID", "").strip()
    return tenant if _SAFE_TENANT.fullmatch(tenant) else ""


def _probe_headers(
    spec: DependencyProbeSpec,
    *,
    correlation_id: str,
    auth_value: str,
    tenant_id: str,
) -> dict[str, str]:
    headers = {"X-AIVAN-Trace-ID": correlation_id}
    if spec.header_contract == "giraffe-db":
        headers.update(
            {
                "X-Service-Auth": auth_value,
                "X-Service-Tenant-ID": tenant_id,
                "X-GPM-Contract-Version": GPM_PERSISTENCE_CONTRACT_VERSION,
                "X-AIVAN-Correlation-ID": correlation_id,
            }
        )
    elif spec.auth_header_name:
        headers[spec.auth_header_name] = auth_value
    return headers


def _result(
    spec: DependencyProbeSpec,
    *,
    correlation_id: str,
    started: float,
    checked_at: float,
    status: ProbeStatus,
    error_code: str | None,
    expected_version: str | None,
    observed_version: str | None = None,
) -> DependencyProbeResult:
    result = DependencyProbeResult(
        dependency_id=spec.dependency_id,
        contract_version="aivan.dependency-probe.v1",
        criticality=spec.criticality,
        owner=spec.owner,
        expected_version=expected_version,
        observed_version=observed_version,
        status=status,
        error_code=error_code,
        correlation_id=correlation_id,
        checked_at_epoch=checked_at,
        duration_seconds=max(0.0, time.perf_counter() - started),
        stale_after_seconds=spec.stale_after_seconds,
    )
    record_dependency_probe(
        dependency_id=result.dependency_id,
        criticality=result.criticality,
        status=result.status,
        duration_seconds=result.duration_seconds,
    )
    return result


def _probe_one(
    spec: DependencyProbeSpec,
    *,
    correlation_id: str,
    transport: httpx.BaseTransport | None,
    total_timeout_seconds: float,
) -> DependencyProbeResult:
    started = time.perf_counter()
    checked_at = time.time()
    base_url = os.environ.get(spec.base_url_env, "").strip()
    expected = os.environ.get(spec.expected_version_env, "").strip()
    auth_value = (
        os.environ.get(spec.auth_value_env, "").strip() if spec.auth_value_env else ""
    )
    tenant_id = _trusted_probe_tenant(spec)
    if (
        not base_url
        or not expected
        or (spec.auth_value_env and not auth_value)
        or (spec.header_contract == "giraffe-db" and not tenant_id)
    ):
        return _result(
            spec,
            correlation_id=correlation_id,
            started=started,
            checked_at=checked_at,
            status="misconfigured",
            error_code="DEPENDENCY_PROBE_MISCONFIGURED",
            expected_version=expected or None,
        )
    try:
        health_url = _probe_url(base_url, spec.health_path)
        version_url = _probe_url(base_url, spec.version_path)
    except ValueError:
        return _result(
            spec,
            correlation_id=correlation_id,
            started=started,
            checked_at=checked_at,
            status="misconfigured",
            error_code="DEPENDENCY_PROBE_MISCONFIGURED",
            expected_version=expected,
        )
    headers = _probe_headers(
        spec,
        correlation_id=correlation_id,
        auth_value=auth_value,
        tenant_id=tenant_id,
    )
    deadline = time.perf_counter() + min(spec.timeout_seconds, total_timeout_seconds)

    def remaining_timeout() -> float:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise httpx.ReadTimeout("dependency probe deadline elapsed")
        return remaining

    try:
        with httpx.Client(
            transport=transport,
            follow_redirects=False,
        ) as client:
            health_response = client.get(
                health_url,
                headers=headers,
                timeout=remaining_timeout(),
            )
            health_response.raise_for_status()
            version_response = (
                health_response
                if health_url == version_url
                else client.get(
                    version_url,
                    headers=headers,
                    timeout=remaining_timeout(),
                )
            )
            version_response.raise_for_status()
            health_payload = _response_object(health_response)
            version_payload = _response_object(version_response)
        if not _health_ready(health_payload):
            return _result(
                spec,
                correlation_id=correlation_id,
                started=started,
                checked_at=checked_at,
                status="unavailable",
                error_code="DEPENDENCY_NOT_READY",
                expected_version=expected,
            )
        observed = _version(version_payload, spec.version_keys)
        if observed is None:
            return _result(
                spec,
                correlation_id=correlation_id,
                started=started,
                checked_at=checked_at,
                status="invalid_response",
                error_code="DEPENDENCY_INVALID_RESPONSE",
                expected_version=expected,
            )
        if observed != expected:
            return _result(
                spec,
                correlation_id=correlation_id,
                started=started,
                checked_at=checked_at,
                status="incompatible",
                error_code="DEPENDENCY_VERSION_MISMATCH",
                expected_version=expected,
                observed_version=observed,
            )
        return _result(
            spec,
            correlation_id=correlation_id,
            started=started,
            checked_at=checked_at,
            status="ready",
            error_code=None,
            expected_version=expected,
            observed_version=observed,
        )
    except httpx.TimeoutException:
        status: ProbeStatus = "timeout"
        code = "DEPENDENCY_TIMEOUT"
    except _InvalidProbeResponse:
        status = "invalid_response"
        code = "DEPENDENCY_INVALID_RESPONSE"
    except (httpx.HTTPError, ValueError):
        status = "unavailable"
        code = "DEPENDENCY_UNAVAILABLE"
    return _result(
        spec,
        correlation_id=correlation_id,
        started=started,
        checked_at=checked_at,
        status=status,
        error_code=code,
        expected_version=expected,
    )


def run_dependency_probes(
    *,
    correlation_id: str,
    specs: tuple[DependencyProbeSpec, ...] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[DependencyProbeResult]:
    reject_test_transport_in_production(transport, component="dependency-probe")
    safe_correlation = _correlation_id(correlation_id)
    selected = specs if specs is not None else required_dependency_specs()
    if not selected:
        return []
    total_timeout = probe_total_timeout_seconds()
    batch_started = time.perf_counter()
    checked_at = time.time()
    futures: list[Future[DependencyProbeResult] | None] = []
    for spec in selected:
        if not _PROBE_SLOTS.acquire(blocking=False):
            futures.append(None)
            continue
        submitted = _PROBE_EXECUTOR.submit(
            _probe_one,
            spec,
            correlation_id=safe_correlation,
            transport=transport,
            total_timeout_seconds=total_timeout,
        )
        submitted.add_done_callback(lambda _future: _PROBE_SLOTS.release())
        futures.append(submitted)
    wait([future for future in futures if future is not None], timeout=total_timeout)
    results: list[DependencyProbeResult] = []
    for spec, future in zip(selected, futures, strict=True):
        if future is not None and future.done():
            results.append(future.result())
            continue
        if future is not None:
            future.cancel()
        results.append(
            _result(
                spec,
                correlation_id=safe_correlation,
                started=batch_started,
                checked_at=checked_at,
                status="timeout",
                error_code="DEPENDENCY_TIMEOUT",
                expected_version=os.environ.get(spec.expected_version_env, "").strip() or None,
            )
        )
    return results


def critical_dependencies_ready(results: list[DependencyProbeResult]) -> bool:
    now = time.time()
    critical = [result for result in results if result.criticality == "critical"]
    return bool(critical) and all(result.is_ready_at(now) for result in critical)


def is_dependency_guarded_request(method: str, path: str) -> bool:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    # CI requires every application mutation to be listed. Runtime is stricter:
    # an unknown mutation is guarded until a reviewed N/A rationale is added.
    return mutation_classification(method, path) != "not_applicable"


async def dependency_side_effect_gate(request: Request, call_next):
    """Block production business mutations before any handler side effect."""

    if not is_production() or not is_dependency_guarded_request(request.method, request.url.path):
        return await call_next(request)
    # Do not let an unauthenticated caller turn this gate into a dependency
    # scanner or probe-amplification path. The route dependency remains the
    # response authority, so failed authentication is allowed to continue only
    # far enough to return its normal 4xx without a provider call.
    from aivan.api.request_context import resolve_request_context

    try:
        resolve_request_context(request)
    except HTTPException:
        return await call_next(request)
    correlation_id = _correlation_id(request.headers.get("X-AIVAN-Trace-ID"))
    results = await asyncio.to_thread(
        run_dependency_probes,
        correlation_id=correlation_id,
    )
    if not critical_dependencies_ready(results):
        return JSONResponse(
            status_code=503,
            content={
                "error": "critical_dependency_unavailable",
                "correlation_id": correlation_id,
            },
        )
    return await call_next(request)
