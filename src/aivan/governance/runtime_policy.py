"""Fail-closed production policy for the AIVAN control plane.

This module freezes the Stage A product boundary.  It deliberately does not
implement monitoring, takeover, or giraffe-db consumer cutover (Stages B-D).
It prevents the current application from claiming a production-safe runtime
while mock, fabricated, code-execution, or second-source modes are enabled.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

PRODUCT_ROLE = "monitoring_takeover_control_plane"
BUSINESS_FACT_AUTHORITY = "giraffe-db"
LOCAL_STATE_SCOPE = "control_audit_cache_only"

PROHIBITED_CAPABILITY_FLAGS = (
    "AIVAN_CODE_GENERATION_ENABLED",
    "AIVAN_CODE_EXECUTION_ENABLED",
    "AIVAN_REPOSITORY_WRITE_ENABLED",
    "AIVAN_GIT_OPERATIONS_ENABLED",
)


class RuntimePolicyError(RuntimeError):
    """Raised when a production process violates the frozen product boundary."""

    def __init__(self, failed_checks: tuple[str, ...], component: str) -> None:
        self.failed_checks = failed_checks
        self.component = component
        super().__init__(
            "AIVAN_RUNTIME_POLICY_VIOLATION "
            f"component={component} checks={','.join(failed_checks)}"
        )


def is_production(environment: Mapping[str, str] | None = None) -> bool:
    values = environment if environment is not None else os.environ
    return values.get("AIVAN_ENV", "local").strip().lower() == "production"


def _value(values: Mapping[str, str], name: str, default: str = "") -> str:
    return values.get(name, default).strip().lower()


def production_policy_checks(
    environment: Mapping[str, str] | None = None,
) -> dict[str, bool]:
    """Return named Stage A production checks without exposing secret values."""

    values = environment if environment is not None else os.environ
    if not is_production(values):
        return {"environment_non_production": True}

    capability_flags_disabled = all(
        _value(values, name) not in {"1", "true", "yes", "on"}
        for name in PROHIBITED_CAPABILITY_FLAGS
    )
    return {
        "product_role_control_plane": _value(values, "AIVAN_PRODUCT_ROLE") == PRODUCT_ROLE,
        "business_fact_authority_giraffe_db": _value(
            values, "AIVAN_BUSINESS_FACT_AUTHORITY"
        )
        == BUSINESS_FACT_AUTHORITY,
        "local_state_control_audit_cache_only": _value(values, "AIVAN_LOCAL_STATE_SCOPE")
        == LOCAL_STATE_SCOPE,
        "human_approval_required": _value(values, "AIVAN_REQUIRE_HUMAN_APPROVAL", "true")
        == "true",
        "code_capabilities_disabled": capability_flags_disabled,
        "stub_suppliers_disabled": _value(values, "AIVAN_ALLOW_STUB_SUPPLIERS", "false")
        not in {"1", "true", "yes", "on"},
        "openclaw_mock_disabled": _value(values, "OPENCLAW_MOCK_MODE", "true")
        not in {"1", "true", "yes", "on"},
        "llm_mock_disabled": _value(values, "AIVAN_LLM_PROVIDER") != "mock",
        "gpm_mock_disabled": _value(values, "GPM_LLM_RUNTIME_MODE", "mock") != "mock",
        "web_search_mock_disabled": _value(values, "AIVAN_WEB_SEARCH_PROVIDER", "mock")
        != "mock",
        "marketplace_mock_disabled": _value(values, "AIVAN_ALIBABA_MODE", "mock")
        != "mock",
        "language_mock_disabled": _value(
            values, "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER"
        )
        != "mock",
        "external_model_auto_disabled": _value(
            values, "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED", "false"
        )
        not in {"1", "true", "yes", "on"},
    }


def enforce_runtime_policy(
    *,
    component: str,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Reject a production process before it initializes mutable state."""

    checks = production_policy_checks(environment)
    failed = tuple(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimePolicyError(failed, component)


def reject_test_transport_in_production(transport: object | None, *, component: str) -> None:
    """Prevent process-wide or per-client fake transports in production."""

    if transport is not None and is_production():
        raise RuntimePolicyError(("test_transport_disabled",), component)
