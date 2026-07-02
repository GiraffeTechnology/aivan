import os
import time
from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_provider_name
from aivan.llm.policy import (
    ExternalModelApiRequiresApprovalError,
    LocalModelUnavailableError,
    assert_provider_allowed,
    is_external_provider,
    llm_api_enabled,
)

_provider_instance: LLMProvider | None = None

# Provider-call observers. The benchmark installs one to read what actually ran
# (provider/model, mock fallback, external call) instead of guessing from env.
_call_observers: list = []


def add_call_observer(fn) -> None:
    _call_observers.append(fn)


def remove_call_observer(fn) -> None:
    try:
        _call_observers.remove(fn)
    except ValueError:
        pass


def _emit(event) -> None:
    for fn in list(_call_observers):
        try:
            fn(event)
        except Exception:
            pass


def _model_for(name: str) -> str:
    if name == "ollama":
        return os.environ.get("OLLAMA_MODEL", "")
    if name in ("openai", "chatgpt", "openai_compatible"):
        return os.environ.get("OPENAI_MODEL", "")
    if name in ("anthropic", "claude"):
        return os.environ.get("ANTHROPIC_MODEL", "")
    if name == "qwen":
        return os.environ.get("QWEN_MODEL", "")
    return ""


def _build_provider(name: str) -> LLMProvider:
    if name == "mock":
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider()
    elif name in ("openai", "chatgpt", "openai_compatible"):
        from aivan.llm.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif name in ("anthropic", "claude"):
        from aivan.llm.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif name in ("google", "gemini"):
        from aivan.llm.providers.google_provider import GoogleProvider
        return GoogleProvider()
    elif name == "deepseek":
        from aivan.llm.providers.deepseek_provider import DeepSeekProvider
        return DeepSeekProvider()
    elif name == "qwen":
        from aivan.llm.providers.qwen_provider import QwenProvider
        return QwenProvider()
    elif name == "ollama":
        from aivan.llm.providers.ollama_provider import OllamaProvider
        return OllamaProvider()
    else:
        from aivan.llm.providers.mock_provider import MockLLMProvider
        return MockLLMProvider()

def build_llm_provider(task: str | None = None) -> LLMProvider:
    """Build the configured LLM provider, enforcing the external-model policy.

    Raises ``ExternalModelApiRequiresApprovalError`` when an external provider is
    requested but automatic external calls are disabled and no approval packet is
    active. Local/private-domain providers (mock, ollama) always build.
    """
    name = get_llm_provider_name()
    assert_provider_allowed(name, task)
    return _build_provider(name)


def get_provider() -> LLMProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = _build_provider(get_llm_provider_name())
    return _provider_instance

def reset_provider():
    global _provider_instance
    _provider_instance = None

def llm_complete_json(
    task: str,
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict = None,
    temperature: float = 0.0,
) -> dict:
    from aivan.telemetry.model_usage import ProviderCallEvent, estimate_tokens

    name = get_llm_provider_name()
    # Enforce the private-domain policy before any provider work. An external
    # provider without approval is a hard, auditable stop — never a silent fallback.
    assert_provider_allowed(name, task)
    if not llm_api_enabled():
        # Zero-model regime: no extraction. Callers fall back to deterministic
        # raw-evidence parsing instead of receiving fabricated canonical fields.
        _emit(ProviderCallEvent(task=task, configured_provider=name, used_provider="none",
                                ok=False, error="llm_api_disabled"))
        return {}

    model = _model_for(name)
    started = time.perf_counter()
    provider = get_provider()
    try:
        result = provider.complete_json(task, system_prompt, user_prompt, schema_hint or {}, temperature)
        if not isinstance(result, dict):
            result = {"result": str(result)}
        _emit(ProviderCallEvent(
            task=task, configured_provider=name, used_provider=name, model=model, ok=True,
            fell_back_to_mock=False, external_api_called=is_external_provider(name),
            input_tokens=estimate_tokens(system_prompt) + estimate_tokens(user_prompt),
            output_tokens=estimate_tokens(str(result)),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        ))
        return result
    except ExternalModelApiRequiresApprovalError:
        raise
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        # The mock provider is only ever used when explicitly configured. A
        # local/external provider failure must NOT be masked by a mock fallback
        # (that would make the local-only benchmark meaningless).
        if name == "mock":
            from aivan.llm.providers.mock_provider import MockLLMProvider
            _emit(ProviderCallEvent(task=task, configured_provider=name, used_provider="mock",
                                    model=model, ok=True, fell_back_to_mock=False,
                                    latency_ms=latency_ms))
            return MockLLMProvider().complete_json(task, system_prompt, user_prompt, schema_hint or {}, temperature)
        _emit(ProviderCallEvent(
            task=task, configured_provider=name, used_provider=name, model=model, ok=False,
            fell_back_to_mock=False, external_api_called=is_external_provider(name),
            latency_ms=latency_ms, error=f"{exc.__class__.__name__}: {exc}",
        ))
        raise LocalModelUnavailableError(name, f"{name} provider call failed: {exc}") from exc
