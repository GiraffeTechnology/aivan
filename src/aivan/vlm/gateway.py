"""Policy-gated VLM provider gateway.

Mirrors the LLM policy: an external VLM provider may be built only when external
model APIs are enabled (or a scoped approval is active). The private-domain
baseline keeps ``AIVAN_VLM_PROVIDER=disabled`` and never reaches a hosted VLM.
"""

from __future__ import annotations

import os

from aivan.llm.policy import (
    ExternalModelApiRequiresApprovalError,
    assert_provider_allowed,
    is_external_provider,
    vlm_api_enabled,
)


class VLMDisabledError(RuntimeError):
    """Raised when a VLM call is attempted while VLM support is disabled."""


def get_vlm_provider_name() -> str:
    return os.environ.get("AIVAN_VLM_PROVIDER", "disabled").strip().lower()


def build_vlm_provider(task: str | None = None):
    """Build the configured VLM provider, enforcing policy.

    * ``disabled`` -> raises :class:`VLMDisabledError` (no VLM in this mode).
    * external provider without enablement/approval -> raises
      :class:`ExternalModelApiRequiresApprovalError`.
    """
    name = get_vlm_provider_name()
    if name in {"", "disabled", "none", "off"}:
        raise VLMDisabledError("AIVAN_VLM_PROVIDER is disabled")
    if is_external_provider(name) and not vlm_api_enabled():
        raise ExternalModelApiRequiresApprovalError(name)
    # External VLM providers additionally go through the shared approval gate.
    assert_provider_allowed(name, task)
    raise VLMDisabledError(f"No VLM provider implementation registered for '{name}'")
