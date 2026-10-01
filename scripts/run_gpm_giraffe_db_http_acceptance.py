#!/usr/bin/env python3
"""Run the real GPM-to-giraffe-db HTTP acceptance checks.

The runner never starts services, applies migrations, or prints credentials. It
expects isolated services to be running already. HTTP is accepted only on a
loopback address; non-loopback service endpoints must use HTTPS.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class AcceptanceFailure(RuntimeError):
    """A stable acceptance assertion failure without secret-bearing context."""


@dataclass(frozen=True)
class Settings:
    gpm_url: str
    db_url: str
    tenant_id: str
    gpm_api_key: str
    db_service_auth: str
    idempotency_key: str
    trace_id: str
    cross_tenant_id: str | None
    cross_tenant_api_key: str | None


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AcceptanceFailure(f"required environment variable is missing: {name}")
    return value


def _safe_endpoint(name: str, value: str) -> str:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise AcceptanceFailure(f"{name} is not a valid HTTP endpoint")
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise AcceptanceFailure(f"{name} must use HTTPS outside loopback")
    return value.rstrip("/")


def _db_credential(tenant_id: str) -> str:
    raw = os.getenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", "").strip()
    if raw:
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AcceptanceFailure("tenant service auth JSON is invalid") from exc
        if not isinstance(configured, dict):
            raise AcceptanceFailure("tenant service auth JSON must be an object")
        credential = configured.get(tenant_id)
        if not isinstance(credential, str) or not credential:
            raise AcceptanceFailure("tenant service credential is missing")
        return credential
    return _required("GIRAFFE_DB_SERVICE_AUTH_SECRET")


def load_settings() -> Settings:
    tenant_id = _required("AIVAN_TENANT_ID")
    idempotency_key = os.getenv(
        "GPM_ACCEPTANCE_IDEMPOTENCY_KEY", f"gpm-acceptance-{uuid.uuid4().hex}"
    ).strip()
    trace_id = os.getenv(
        "GPM_ACCEPTANCE_TRACE_ID", f"gpm-acceptance-{uuid.uuid4().hex}"
    ).strip()
    for name, value in {
        "AIVAN_TENANT_ID": tenant_id,
        "GPM_ACCEPTANCE_IDEMPOTENCY_KEY": idempotency_key,
        "GPM_ACCEPTANCE_TRACE_ID": trace_id,
    }.items():
        if not SAFE_VALUE.fullmatch(value):
            raise AcceptanceFailure(f"{name} contains unsupported characters")
    cross_tenant_id = os.getenv("GPM_CROSS_TENANT_ID", "").strip() or None
    cross_tenant_api_key = os.getenv("GPM_CROSS_TENANT_API_KEY", "").strip() or None
    if bool(cross_tenant_id) != bool(cross_tenant_api_key):
        raise AcceptanceFailure(
            "GPM_CROSS_TENANT_ID and GPM_CROSS_TENANT_API_KEY must be supplied together"
        )
    return Settings(
        gpm_url=_safe_endpoint("GPM_API_BASE_URL", _required("GPM_API_BASE_URL")),
        db_url=_safe_endpoint("GIRAFFE_DB_BASE_URL", _required("GIRAFFE_DB_BASE_URL")),
        tenant_id=tenant_id,
        gpm_api_key=_required("GPM_API_KEY"),
        db_service_auth=_db_credential(tenant_id),
        idempotency_key=idempotency_key,
        trace_id=trace_id,
        cross_tenant_id=cross_tenant_id,
        cross_tenant_api_key=cross_tenant_api_key,
    )


def _json(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise AcceptanceFailure(f"{operation} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceFailure(f"{operation} returned a non-object response")
    return value


def _expect_status(
    response: httpx.Response, expected: set[int], operation: str
) -> dict[str, Any]:
    if response.status_code not in expected:
        raise AcceptanceFailure(
            f"{operation} returned HTTP {response.status_code}, expected {sorted(expected)}"
        )
    return _json(response, operation)


def _gpm_headers(settings: Settings) -> dict[str, str]:
    return {
        "X-AIVAN-API-Key": settings.gpm_api_key,
        "X-AIVAN-Tenant-ID": settings.tenant_id,
        "X-AIVAN-Trace-ID": settings.trace_id,
        "Idempotency-Key": settings.idempotency_key,
    }


def _db_headers(settings: Settings, *, tenant_id: str | None = None) -> dict[str, str]:
    return {
        "X-Service-Tenant-ID": tenant_id or settings.tenant_id,
        "X-Service-Auth": settings.db_service_auth,
        "X-AIVAN-Correlation-ID": settings.trace_id,
    }


def _payload() -> dict[str, Any]:
    return {
        "sku": os.getenv("GPM_ACCEPTANCE_SKU", "SYNTH-GPM-001"),
        "supplier_id": os.getenv("GPM_ACCEPTANCE_SUPPLIER_ID", "synthetic-supplier-001"),
        "supplier_quote": float(os.getenv("GPM_ACCEPTANCE_SUPPLIER_QUOTE", "12.5")),
        "currency": os.getenv("GPM_ACCEPTANCE_CURRENCY", "USD"),
        "quantity": int(os.getenv("GPM_ACCEPTANCE_QUANTITY", "100")),
        "evidence_ids": ["synthetic-evidence-001"],
        "notes": "isolated synthetic GPM acceptance input",
    }


def _assert_packet(packet: dict[str, Any], settings: Settings) -> str:
    packet_id = packet.get("packet_id")
    if (
        not isinstance(packet_id, str)
        or not packet_id.startswith("gpm_pkt_")
        or packet.get("tenant_id") != settings.tenant_id
        or packet.get("human_approval_required") is not True
        or packet.get("approval_status") != "pending"
        or packet.get("dispatched") is not False
        or not isinstance(packet.get("recommendation"), str)
        or not isinstance(packet.get("quote_position"), str)
        or not isinstance(packet.get("confidence"), str)
    ):
        raise AcceptanceFailure("GPM returned an invalid guidance packet")
    reasoning = packet.get("llm_reasoning")
    if isinstance(reasoning, str):
        try:
            reasoning = json.loads(reasoning)
        except json.JSONDecodeError:
            reasoning = None
    if isinstance(reasoning, dict) and reasoning.get("runtime_status") == "unavailable":
        raise AcceptanceFailure("GPM used an unavailable model runtime")
    return packet_id


def provider_preflight(client: httpx.Client, settings: Settings) -> None:
    schema = _expect_status(
        client.get(
            f"{settings.db_url}/api/data/schema-version",
            headers=_db_headers(settings),
        ),
        {200},
        "giraffe-db schema probe",
    )
    if not isinstance(schema.get("schema_version"), str):
        raise AcceptanceFailure("giraffe-db schema identity is missing")
    capabilities = _expect_status(
        client.get(
            f"{settings.db_url}/api/data/gpm/capabilities",
            headers=_db_headers(settings),
        ),
        {200},
        "giraffe-db GPM capability probe",
    )
    required = {"create_packet", "read_packet", "idempotent_create"}
    advertised = capabilities.get("capabilities")
    if (
        capabilities.get("api_version") != "gpm.packet-persistence.v1"
        or not isinstance(advertised, dict)
        or any(advertised.get(item) is not True for item in required)
    ):
        raise AcceptanceFailure("giraffe-db GPM capabilities do not match")


def readback(
    client: httpx.Client, settings: Settings, packet_id: str
) -> dict[str, Any]:
    gpm_packet = _expect_status(
        client.get(
            f"{settings.gpm_url}/api/gpm/quote-guidance/{packet_id}",
            headers=_gpm_headers(settings),
        ),
        {200},
        "GPM readback",
    )
    db_packet = _expect_status(
        client.get(
            f"{settings.db_url}/api/data/gpm/packets/{packet_id}",
            headers=_db_headers(settings),
        ),
        {200},
        "giraffe-db readback",
    )
    if gpm_packet != db_packet:
        raise AcceptanceFailure("GPM and giraffe-db readback packets differ")
    _assert_packet(gpm_packet, settings)
    return gpm_packet


def cross_tenant_negative(
    client: httpx.Client, settings: Settings, packet_id: str
) -> None:
    if settings.cross_tenant_id and settings.cross_tenant_api_key:
        headers = {
            "X-AIVAN-API-Key": settings.cross_tenant_api_key,
            "X-AIVAN-Tenant-ID": settings.cross_tenant_id,
            "X-AIVAN-Trace-ID": settings.trace_id,
            "Idempotency-Key": settings.idempotency_key,
        }
        response = client.get(
            f"{settings.gpm_url}/api/gpm/quote-guidance/{packet_id}",
            headers=headers,
        )
        if response.status_code not in {403, 404}:
            raise AcceptanceFailure(
                "cross-tenant GPM read did not fail closed with 403 or 404"
            )

    wrong_tenant = settings.cross_tenant_id or f"{settings.tenant_id}-unauthorized"
    response = client.get(
        f"{settings.db_url}/api/data/gpm/packets/{packet_id}",
        headers=_db_headers(settings, tenant_id=wrong_tenant),
    )
    if response.status_code != 403:
        raise AcceptanceFailure("cross-tenant provider credential was not rejected")


def run_full(client: httpx.Client, settings: Settings) -> str:
    provider_preflight(client, settings)
    payload = _payload()
    first = _expect_status(
        client.post(
            f"{settings.gpm_url}/api/gpm/quote-guidance",
            headers=_gpm_headers(settings),
            json=payload,
        ),
        {201},
        "GPM create",
    )
    packet_id = _assert_packet(first, settings)
    replay = _expect_status(
        client.post(
            f"{settings.gpm_url}/api/gpm/quote-guidance",
            headers=_gpm_headers(settings),
            json=payload,
        ),
        {201},
        "GPM replay",
    )
    if replay != first:
        raise AcceptanceFailure("same-key GPM replay changed the response")

    conflict_payload = {**payload, "supplier_quote": payload["supplier_quote"] + 1.0}
    conflict = client.post(
        f"{settings.gpm_url}/api/gpm/quote-guidance",
        headers=_gpm_headers(settings),
        json=conflict_payload,
    )
    conflict_body = _expect_status(conflict, {409}, "GPM idempotency conflict")
    detail = conflict_body.get("detail", conflict_body)
    if not isinstance(detail, dict) or detail.get("error") != "GPM_IDEMPOTENCY_CONFLICT":
        raise AcceptanceFailure("GPM idempotency conflict code is unstable")

    persisted = readback(client, settings, packet_id)
    if persisted != first:
        raise AcceptanceFailure("persisted packet differs from the create response")
    cross_tenant_negative(client, settings, packet_id)
    return packet_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run real GPM and giraffe-db HTTP acceptance checks."
    )
    parser.add_argument(
        "--phase",
        choices=("full", "readback"),
        default="full",
        help="Use readback after restarting both service processes.",
    )
    parser.add_argument(
        "--packet-id",
        help="Previously reported packet ID; required for the readback phase.",
    )
    args = parser.parse_args()
    try:
        settings = load_settings()
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            if args.phase == "full":
                packet_id = run_full(client, settings)
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "phase": "full",
                            "packet_id": packet_id,
                            "next": "restart services, then run --phase readback --packet-id <packet_id>",
                        },
                        sort_keys=True,
                    )
                )
            else:
                if not args.packet_id or not SAFE_VALUE.fullmatch(args.packet_id):
                    raise AcceptanceFailure("a safe --packet-id is required for readback")
                provider_preflight(client, settings)
                readback(client, settings, args.packet_id)
                cross_tenant_negative(client, settings, args.packet_id)
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "phase": "readback",
                            "packet_id": args.packet_id,
                        },
                        sort_keys=True,
                    )
                )
        return 0
    except (AcceptanceFailure, httpx.HTTPError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
