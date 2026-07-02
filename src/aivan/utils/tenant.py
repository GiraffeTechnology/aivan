"""Unified, fail-closed service-tenant resolver.

Every AIVAN subsystem that talks to a shared private-domain service (GLTG v2,
giraffe-db graph persistence, the language skill, GPM) MUST resolve the service
tenant through this single module. No module may invent its own tenant fallback
chain — that is how AIVAN, GLTG, and giraffe-db end up disagreeing about which
tenant a record belongs to, or worse, stamping one tenant's business facts under
a shared placeholder.

Multi-tenant procurement work must never silently guess a tenant. When tenant
scope is required, it must come from a verified source, or the operation fails
closed with a typed :class:`TenantResolutionError`. Two verified sources that
disagree raise :class:`TenantMismatchError` (cross-tenant access is rejected,
never silently reconciled).

Resolution priority (highest first):
    1. explicit ``AIVAN_TENANT_ID``
    2. ``GIRAFFE_DB_TENANT_ID``
    3. ``GIRAFFE_TENANT_ID``
    4. verified channel binding / project (passed by callers that have it)
    5. operator-confirmed tenant (passed by callers that have it)
    6. fail closed

A test-mode fallback tenant is permitted ONLY when ``AIVAN_TEST_MODE=true`` and
``AIVAN_TEST_TENANT_ID`` is set; it is never available in production.
"""

from __future__ import annotations

import logging
import os
import warnings

logger = logging.getLogger(__name__)

TENANT_RESOLUTION_REQUIRED = "TENANT_RESOLUTION_REQUIRED"
TENANT_MISMATCH = "TENANT_MISMATCH"

# Ordered env vars for the service-tenant chain.
_SERVICE_TENANT_ENV_VARS = ("AIVAN_TENANT_ID", "GIRAFFE_DB_TENANT_ID", "GIRAFFE_TENANT_ID")


class TenantResolutionError(RuntimeError):
    """No verified tenant could be resolved and no valid fallback applies."""

    error_code = TENANT_RESOLUTION_REQUIRED


class TenantMismatchError(RuntimeError):
    """Two verified sources disagree on the tenant (cross-tenant access)."""

    error_code = TENANT_MISMATCH


def is_test_mode() -> bool:
    return os.environ.get("AIVAN_TEST_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _test_tenant() -> str | None:
    value = os.environ.get("AIVAN_TEST_TENANT_ID")
    return value.strip() if value and value.strip() else None


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

    Any two provided sources that disagree raise :class:`TenantMismatchError`.
    The test fallback is used only when ``allow_test_fallback`` (defaulting to
    :func:`is_test_mode`) is true and a ``test_tenant`` is configured.
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
        f"{TENANT_RESOLUTION_REQUIRED}: no verified tenant for {context}; refusing "
        "to guess. Provide AIVAN_TENANT_ID / GIRAFFE_DB_TENANT_ID / GIRAFFE_TENANT_ID, "
        "a verified channel/case binding, or an operator-confirmed mapping."
    )


def resolve_service_tenant(context: str = "service_call") -> str:
    """Resolve the tenant for AIVAN → giraffe-db / GLTG service calls.

    Honors the explicit env chain, then the sanctioned test fallback, then fails
    closed. Never returns a shared placeholder tenant.
    """
    explicit = next(
        (os.environ[name].strip() for name in _SERVICE_TENANT_ENV_VARS
         if os.environ.get(name) and os.environ[name].strip()),
        None,
    )
    return resolve_tenant(explicit=explicit, test_tenant=_test_tenant(), context=context)


def resolve_service_tenant_id() -> str:
    """Backward-compatible alias for the service-tenant resolver.

    Kept so existing call sites keep one import; delegates to the fail-closed
    :func:`resolve_service_tenant`.
    """
    return resolve_service_tenant(context="service_tenant_id")
