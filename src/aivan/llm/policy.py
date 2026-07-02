"""Private-domain external-model API policy gates.

The private-domain product baseline must close the RFQ loop without calling any
external (third-party hosted) model provider API. External provider APIs are not
absolutely forbidden — they are a *controlled escalation* that requires an
explicit, auditable approval packet (see PRD §14A/§15). This module centralizes:

  * classification of a provider as external vs private-domain-local,
  * the policy flags that disable *automatic* external calls,
  * a per-thread approval registry so a confirmed ``external_model_call`` packet
    can authorize one scoped external call,
  * ``ExternalModelApiRequiresApprovalError`` raised when code tries to reach an
    external provider without approval.

Nothing here silently falls back to a cloud provider or returns ``{}`` — the
error is surfaced so dependency policy can turn it into a structured operator
message instead of a generic backend error.
"""

from __future__ import annotations

import contextlib
import os
import threading
import uuid
from dataclasses import dataclass, field

# Providers that live inside the tenant/private deployment boundary. Everything
# else that reaches a hosted third-party API is "external".
LOCAL_PROVIDERS = frozenset({"mock", "ollama", "disabled"})
EXTERNAL_PROVIDERS = frozenset(
    {"openai", "chatgpt", "openai_compatible", "anthropic", "claude", "google", "gemini", "deepseek", "qwen"}
)

EXTERNAL_MODEL_API_REQUIRES_EXPLICIT_CONFIRMATION = (
    "EXTERNAL_MODEL_API_REQUIRES_EXPLICIT_CONFIRMATION"
)


class LocalModelUnavailableError(RuntimeError):
    """Raised when a configured private-domain local model (e.g. Ollama) fails.

    AIVAN must never mask a local-model failure by silently falling back to the
    mock provider — that would make a local-only benchmark meaningless (a dead
    Ollama could look like success). Dependency policy converts this into a
    structured recovery / reduced-strength state instead.
    """

    def __init__(self, provider: str, message: str | None = None) -> None:
        self.provider = provider
        super().__init__(message or f"LOCAL_MODEL_UNAVAILABLE: provider={provider}")


# Alias per PR nomenclature.
LocalLLMCallFailed = LocalModelUnavailableError


class ExternalModelApiRequiresApprovalError(RuntimeError):
    """Raised when an external model provider is requested without approval.

    Dependency policy catches this and renders a structured operator message; it
    must never surface as a generic backend error.
    """

    code = EXTERNAL_MODEL_API_REQUIRES_EXPLICIT_CONFIRMATION

    def __init__(self, provider: str, message: str | None = None) -> None:
        self.provider = provider
        super().__init__(
            message
            or f"{EXTERNAL_MODEL_API_REQUIRES_EXPLICIT_CONFIRMATION}: provider={provider}"
        )


@dataclass
class ExternalModelApproval:
    """A confirmed approval to call an external model for one scoped task."""

    task: str
    provider: str
    model: str = ""
    reason: str = ""
    redaction_policy: str = "none"
    operator_id: str = ""
    tenant_id: str = ""
    approval_id: str = field(default_factory=lambda: f"ext_appr_{uuid.uuid4().hex[:12]}")
    status: str = "approved"


# Per-thread stack of active approvals. A confirmed call installs one here for
# the scope of the external request only, so approval can never become a silent,
# process-wide fallback.
_local = threading.local()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_external_provider(provider: str | None) -> bool:
    return (provider or "").strip().lower() in EXTERNAL_PROVIDERS


def external_model_api_enabled() -> bool:
    """Whether the external model provider connector is available at all.

    NOTE: this only means "the connector may be built"; it does NOT authorize
    automatic calls. Every external call still requires an approval packet unless
    ``AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED`` is explicitly true.
    """
    return _env_bool("AIVAN_EXTERNAL_MODEL_API_ENABLED", False)


def external_model_api_auto_allowed() -> bool:
    """Whether external calls may proceed WITHOUT a per-call approval packet.

    False by default and must never be true in the private-domain baseline.
    """
    return _env_bool("AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED", False)


def llm_api_enabled() -> bool:
    """Whether LLM calls (local or external) are enabled for AIVAN."""
    return _env_bool("AIVAN_LLM_API_ENABLED", True)


def vlm_api_enabled() -> bool:
    return _env_bool("AIVAN_VLM_API_ENABLED", False)


def _active_approvals() -> list[ExternalModelApproval]:
    return getattr(_local, "approvals", [])


@contextlib.contextmanager
def external_model_approval(approval: ExternalModelApproval):
    """Authorize external calls for the current thread within this scope."""
    stack = getattr(_local, "approvals", None)
    if stack is None:
        stack = []
        _local.approvals = stack
    stack.append(approval)
    try:
        yield approval
    finally:
        stack.pop()


def has_active_external_approval(provider: str, task: str | None = None) -> bool:
    """Whether a confirmed, in-scope approval is active for this thread.

    A task-scoped approval matches only when the *same* task is requested, so an
    approval for one task never leaks to another.
    """
    provider = (provider or "").strip().lower()
    for appr in _active_approvals():
        if appr.status != "approved":
            continue
        if appr.provider.strip().lower() not in {provider, "any", "*"}:
            continue
        if appr.task in {"any", "*"}:
            return True
        if task is not None and task == appr.task:
            return True
    return False


def assert_provider_allowed(provider: str, task: str | None = None) -> None:
    """Raise unless the provider may be reached under current policy.

    Local/private-domain providers are always allowed. External providers ALWAYS
    require an explicit per-call approval packet by default — merely enabling the
    connector (``AIVAN_EXTERNAL_MODEL_API_ENABLED=true``) is not authorization.
    The only way to skip per-call approval is the explicit, non-default override
    ``AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED=true`` (never in private-domain mode).
    """
    if not is_external_provider(provider):
        return
    if has_active_external_approval(provider, task):
        return
    if external_model_api_enabled() and external_model_api_auto_allowed():
        return
    raise ExternalModelApiRequiresApprovalError(provider)
