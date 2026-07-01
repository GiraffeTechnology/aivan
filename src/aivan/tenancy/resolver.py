"""Tenant resolution for AIVAN.

Multi-tenant procurement work must never silently guess a tenant. When a
business read/write requires tenant scope, the tenant must come from a verified
source, or the operation must fail closed.

Resolution order (highest priority first):
    1. Explicit tenant_id from authenticated / request context.
    2. Tenant derived from a verified channel-account binding.
    3. Tenant derived from verified project / procurement_case ownership.
    4. Tenant derived from an operator-confirmed mapping.
    5. Otherwise: fail closed (:class:`TenantResolutionError`).

A test-mode fallback tenant is allowed ONLY when ``AIVAN_TEST_MODE`` is enabled
and a fallback is explicitly configured; it emits a warning and is never used in
production mode.
"""
from __future__ import annotations

import logging
import os
import warnings

logger = logging.getLogger(__name__)

TENANT_RESOLUTION_REQUIRED = "TENANT_RESOLUTION_REQUIRED"
TENANT_MISMATCH = "TENANT_MISMATCH"


class TenantResolutionError(RuntimeError):
    """No verified tenant could be resolved and no valid fallback applies."""

    error_code = TENANT_RESOLUTION_REQUIRED


class TenantMismatchError(RuntimeError):
    """Two verified sources disagree on the tenant (cross-tenant access)."""

    error_code = TENANT_MISMATCH


def is_test_mode() -> bool:
    return os.environ.get("AIVAN_TEST_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def resolve_tenant(
    *,
    explicit: str | None = None,
    channel_binding: str | None = None,
    case_ownership: str | None = None,
    operator_confirmed: str | None = None,
    test_tenant: str | None = None,
    allow_test_fallback: bool | None = None,
    context: str = "operation",
) -> str:
    """Resolve a tenant id, failing closed when none can be verified.

    Any two provided sources that disagree raise :class:`TenantMismatchError`
    (cross-tenant access is rejected rather than silently picking one).
    """
    ordered = [
        ("explicit", explicit),
        ("channel_binding", channel_binding),
        ("case_ownership", case_ownership),
        ("operator_confirmed", operator_confirmed),
    ]
    provided = [(name, value.strip()) for name, value in ordered if value and value.strip()]

    if provided:
        chosen_name, chosen = provided[0]
        for name, value in provided[1:]:
            if value != chosen:
                raise TenantMismatchError(
                    f"{TENANT_MISMATCH}: {context} tenant sources disagree "
                    f"({chosen_name}={chosen!r} vs {name}={value!r})"
                )
        return chosen

    if allow_test_fallback is None:
        allow_test_fallback = is_test_mode()
    if allow_test_fallback and test_tenant and test_tenant.strip():
        message = (
            f"Using configured test-mode fallback tenant for {context}; "
            "this must never happen in production."
        )
        warnings.warn(message, stacklevel=2)
        logger.warning(message)
        return test_tenant.strip()

    raise TenantResolutionError(
        f"{TENANT_RESOLUTION_REQUIRED}: no verified tenant for {context}; "
        "refusing to guess a tenant. Provide an explicit tenant, a verified "
        "channel/account or case binding, or an operator-confirmed mapping."
    )


def resolve_service_tenant(context: str = "giraffe_db_write") -> str:
    """Resolve the tenant for AIVAN → giraffe-db / GLTG service calls.

    Honors an explicit ``AIVAN_TENANT_ID`` / ``GIRAFFE_DB_TENANT_ID``. When
    absent, only a ``AIVAN_TEST_TENANT_ID`` under ``AIVAN_TEST_MODE`` is
    permitted; otherwise this fails closed instead of defaulting to a shared
    placeholder tenant.
    """
    explicit = os.environ.get("AIVAN_TENANT_ID") or os.environ.get("GIRAFFE_DB_TENANT_ID")
    return resolve_tenant(
        explicit=explicit or None,
        test_tenant=os.environ.get("AIVAN_TEST_TENANT_ID") or None,
        context=context,
    )
